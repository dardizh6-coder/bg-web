from __future__ import annotations

import io
import json
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.admin import router as admin_router
from app.backgrounds import generate_background, list_backgrounds
from app.config import settings
from app.db import Db
from app.image_processing import RenderParams, clamp_preview, encode_image, render_composite
from app.storage import cutouts_dir, db_path, ensure_dirs, originals_dir, safe_filename
from app.stripe_payments import create_checkout_session, handle_webhook, stripe_configured, sync_payment_from_session
from app.worker import remove_background_to_file


app = FastAPI(title="Car Photo Processor", version="1.0.0")

if getattr(settings, "CORS_ORIGINS", None):
    origins = settings.CORS_ORIGINS
    allow_credentials = False if "*" in origins else True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else [],
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(admin_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def _require_secret() -> None:
    if settings.APP_ENV != "development" and not settings.APP_SECRET:
        raise RuntimeError("APP_SECRET must be set")


@app.on_event("startup")
def _startup() -> None:
    ensure_dirs()
    _require_secret()
    db = Db(path=db_path())
    db.init()
    app.state.db = db
    app.state.executor = ThreadPoolExecutor(max_workers=max(1, int(getattr(settings, "MAX_WORKERS", 1) or 1)))
    # Rembg model session is loaded lazily on first job (prevents slow/OOM startup on small containers).
    app.state.rembg_session = None
    db.log("info", "app.start", f"env={settings.APP_ENV} workers={getattr(settings, 'MAX_WORKERS', 1)} model={settings.RMBG_MODEL}")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


def _client_token(request: Request) -> str | None:
    # Cross-domain frontend hosting: allow token via query parameter for <img>/<canvas> loads.
    tok = request.query_params.get("token")
    if tok:
        return tok
    tok = request.cookies.get("client_token")
    if tok:
        return tok
    # Fallback: allow token via header for dev/testing.
    return request.headers.get("x-client-token")


def _paid(request: Request) -> bool:
    tok = _client_token(request)
    if not tok:
        return False
    db: Db = request.app.state.db
    c = db.get_client(tok)
    return bool(c and c.get("paid") == 1)


class RegisterClientIn(BaseModel):
    token: str = Field(min_length=8, max_length=128)


@app.post("/api/client/register")
def register_client(request: Request, body: RegisterClientIn) -> JSONResponse:
    db: Db = request.app.state.db
    db.upsert_client(body.token)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        "client_token",
        body.token,
        httponly=True,
        samesite="lax",
        secure=settings.PUBLIC_BASE_URL.startswith("https://"),
        max_age=60 * 60 * 24 * 365,
    )
    return resp


@app.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    tok = _client_token(request)
    db: Db = request.app.state.db
    if tok:
        db.upsert_client(tok)
    return {
        "paid": _paid(request),
        "adsense": {"client": settings.ADSENSE_CLIENT, "slot": settings.ADSENSE_SLOT},
        "stripe_configured": stripe_configured(),
    }


@app.get("/api/backgrounds")
def list_backgrounds() -> dict[str, Any]:
    return {
        "backgrounds": [
            {
                "id": b.id,
                "name": b.name,
                "description": b.description,
                "thumb_url": f"/api/backgrounds/{b.id}/thumb.png",
            }
            for b in list_backgrounds()
        ]
    }


@app.get("/api/backgrounds/{bg_id}/thumb.png")
def background_thumb(bg_id: str) -> Response:
    from PIL import Image

    try:
        img = generate_background(bg_id, (900, 560))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown background")
    out = encode_image(img.convert("RGBA"), "png")
    return Response(content=out, media_type="image/png")


class CreateJobOut(BaseModel):
    job_id: str
    images: list[dict[str, Any]]


@app.post("/api/jobs", response_model=CreateJobOut)
async def create_job(request: Request, files: list[UploadFile] = File(...)) -> Any:
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token (register first).")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    db: Db = request.app.state.db
    db.upsert_client(tok)

    job_id = str(uuid.uuid4())
    now = int(time.time())
    with db.connect() as conn:
        conn.execute("INSERT INTO jobs(id, client_token, created_at) VALUES(?,?,?)", (job_id, tok, now))
        conn.commit()

    results: list[dict[str, Any]] = []
    for f in files:
        image_id = str(uuid.uuid4())
        fname = safe_filename(f.filename or "upload.jpg")
        original_path = originals_dir() / f"{image_id}_{fname}"
        cutout_path = cutouts_dir() / f"{image_id}.png"

        # Stream upload to disk (avoid reading full file into RAM on Railway)
        await f.seek(0)
        with original_path.open("wb") as out:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO images(id, job_id, filename, created_at, status, original_path, cutout_path)
                VALUES(?,?,?,?,?,?,?)
                """,
                (image_id, job_id, fname, now, "queued", str(original_path), str(cutout_path)),
            )
            conn.commit()

        results.append(
            {
                "id": image_id,
                "filename": fname,
                "status": "queued",
                "original_url": f"/api/images/{image_id}/original",
                "cutout_url": f"/api/images/{image_id}/cutout.png",
            }
        )

        def _mark_processing(img_id: str = image_id) -> None:
            with db.connect() as conn:
                conn.execute("UPDATE images SET status='processing' WHERE id=?", (img_id,))
                conn.commit()

        def _on_success(width: int, height: int, img_id: str = image_id) -> None:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE images SET status='ready', width=?, height=?, error=NULL WHERE id=?",
                    (width, height, img_id),
                )
                conn.commit()
            db.log("info", "image.ready", f"image={img_id} {width}x{height}")

        def _on_error(detail: str, img_id: str = image_id) -> None:
            with db.connect() as conn:
                conn.execute("UPDATE images SET status='error', error=? WHERE id=?", (detail, img_id))
                conn.commit()
            db.log("error", "image.error", f"image={img_id}\n{detail}")

        _mark_processing()
        request.app.state.executor.submit(
            remove_background_to_file,
            original_path=original_path,
            cutout_path=cutout_path,
            session=request.app.state.rembg_session,
            on_error=_on_error,
            on_success=_on_success,
        )

    db.log("info", "job.created", f"job={job_id} images={len(results)} client={tok}")
    return {"job_id": job_id, "images": results}


@app.get("/api/jobs/{job_id}")
def job_status(request: Request, job_id: str) -> dict[str, Any]:
    db: Db = request.app.state.db
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")

    with db.connect() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? AND client_token=?", (job_id, tok)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        imgs = conn.execute("SELECT * FROM images WHERE job_id=? ORDER BY created_at ASC", (job_id,)).fetchall()

    images = []
    for r in imgs:
        images.append(
            {
                "id": r["id"],
                "filename": r["filename"],
                "status": r["status"],
                "error": r["error"],
                "width": r["width"],
                "height": r["height"],
                "original_url": f"/api/images/{r['id']}/original",
                "cutout_url": f"/api/images/{r['id']}/cutout.png",
            }
        )

    return {"job_id": job_id, "images": images}


@app.get("/api/images/{image_id}/original")
def get_original(request: Request, image_id: str) -> FileResponse:
    db: Db = request.app.state.db
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT i.original_path FROM images i
            JOIN jobs j ON j.id = i.job_id
            WHERE i.id=? AND j.client_token=?
            """,
            (image_id, tok),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(row["original_path"])


@app.get("/api/images/{image_id}/cutout.png")
def get_cutout(request: Request, image_id: str) -> FileResponse:
    db: Db = request.app.state.db
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT i.cutout_path, i.status FROM images i
            JOIN jobs j ON j.id = i.job_id
            WHERE i.id=? AND j.client_token=?
            """,
            (image_id, tok),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if row["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"Cutout not ready (status={row['status']})")
    return FileResponse(row["cutout_path"], media_type="image/png")


def _load_cutout(db: Db, tok: str, image_id: str) -> Path:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT i.cutout_path, i.status FROM images i
            JOIN jobs j ON j.id = i.job_id
            WHERE i.id=? AND j.client_token=?
            """,
            (image_id, tok),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    if row["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"Image not ready (status={row['status']})")
    return Path(row["cutout_path"])


@app.get("/api/render/preview")
def render_preview(
    request: Request,
    image_id: str,
    bg_id: str,
    rotate: float = 0.0,
    scale: float = 1.0,
    x: float = 0.0,
    y: float = 0.0,
    shadow: bool = True,
    snap: bool = False,
    fmt: str = "png",
) -> Response:
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")

    db: Db = request.app.state.db
    cutout_path = _load_cutout(db, tok, image_id)

    from PIL import Image

    with Image.open(cutout_path) as car:
        car = car.convert("RGBA")
        bg = generate_background(bg_id, car.size)
        params = RenderParams(rotate_deg=rotate, scale=scale, offset_x=x, offset_y=y, shadow=shadow, snap_center=snap)
        out = render_composite(car, bg, params, paid=_paid(request))
        out = clamp_preview(out, max_dim=1200)
        data = encode_image(out, fmt)
        media = "image/png" if fmt.lower() == "png" else "image/jpeg"
        return Response(content=data, media_type=media)


@app.get("/api/render/download")
def render_download(
    request: Request,
    image_id: str,
    bg_id: str,
    rotate: float = 0.0,
    scale: float = 1.0,
    x: float = 0.0,
    y: float = 0.0,
    shadow: bool = True,
    snap: bool = False,
    fmt: str = "jpg",
) -> Response:
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")

    db: Db = request.app.state.db
    cutout_path = _load_cutout(db, tok, image_id)

    from PIL import Image

    with Image.open(cutout_path) as car:
        car = car.convert("RGBA")
        bg = generate_background(bg_id, car.size)
        params = RenderParams(rotate_deg=rotate, scale=scale, offset_x=x, offset_y=y, shadow=shadow, snap_center=snap)
        out = render_composite(car, bg, params, paid=_paid(request))
        data = encode_image(out, fmt)

    media = "image/png" if fmt.lower() == "png" else "image/jpeg"
    ext = "png" if fmt.lower() == "png" else "jpg"
    headers = {"Content-Disposition": f'attachment; filename="{image_id}.{ext}"'}
    return Response(content=data, media_type=media, headers=headers)


class ZipItem(BaseModel):
    image_id: str
    bg_id: str
    rotate: float = 0.0
    scale: float = 1.0
    x: float = 0.0
    y: float = 0.0
    shadow: bool = True
    snap: bool = False


class ZipIn(BaseModel):
    items: list[ZipItem]
    fmt: str = "jpg"


@app.post("/api/render/zip")
def render_zip(request: Request, body: ZipIn) -> StreamingResponse:
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")
    if not body.items:
        raise HTTPException(status_code=400, detail="No items")

    db: Db = request.app.state.db
    paid = _paid(request)

    from PIL import Image

    # Spool to disk if zip grows large.
    import tempfile

    tmp = tempfile.SpooledTemporaryFile(max_size=50_000_000)
    with zipfile.ZipFile(tmp, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for it in body.items:
            cutout_path = _load_cutout(db, tok, it.image_id)
            with Image.open(cutout_path) as car:
                car = car.convert("RGBA")
                bg = generate_background(it.bg_id, car.size)
                params = RenderParams(
                    rotate_deg=it.rotate,
                    scale=it.scale,
                    offset_x=it.x,
                    offset_y=it.y,
                    shadow=it.shadow,
                    snap_center=it.snap,
                )
                out = render_composite(car, bg, params, paid=paid)
                data = encode_image(out, body.fmt)

            ext = "png" if body.fmt.lower() == "png" else "jpg"
            zf.writestr(f"{it.image_id}.{ext}", data)

    tmp.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="aucto_processed.zip"'}
    return StreamingResponse(tmp, media_type="application/zip", headers=headers)


class CheckoutOut(BaseModel):
    url: str


@app.post("/api/stripe/create-checkout", response_model=CheckoutOut)
def stripe_create_checkout(request: Request) -> Any:
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")
    try:
        url = create_checkout_session(tok)
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/stripe/checkout-status")
def stripe_checkout_status(request: Request, session_id: str) -> dict[str, Any]:
    db: Db = request.app.state.db
    tok = _client_token(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Missing client token")
    try:
        info = sync_payment_from_session(db, session_id=session_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    # If the session belongs to a different token, do not flip this browser.
    if info.get("client_token") != tok:
        return {"paid": _paid(request), "note": "Payment belongs to another client token."}
    return {"paid": _paid(request)}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request) -> Response:
    db: Db = request.app.state.db
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        handle_webhook(db, payload=payload, sig_header=sig)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content=b"ok", media_type="text/plain")

