from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import Db
from app.security import sign_dict, verify_signed_dict


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _is_admin(request: Request) -> bool:
    tok = request.cookies.get("admin_session")
    if not tok or not settings.APP_SECRET:
        return False
    payload = verify_signed_dict(tok, settings.APP_SECRET)
    return bool(payload and payload.get("admin") is True)


@router.get("/admin", response_class=HTMLResponse)
def admin_login_page(request: Request) -> HTMLResponse:
    if _is_admin(request):
        return RedirectResponse("/admin/dashboard", status_code=302)
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": None},
    )


@router.post("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request, password: str = Form(...)) -> HTMLResponse:
    if not settings.APP_SECRET:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "APP_SECRET is not set."},
            status_code=500,
        )
    if not settings.ADMIN_PASSWORD:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "ADMIN_PASSWORD is not set."},
            status_code=500,
        )
    if password != settings.ADMIN_PASSWORD:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Wrong password."},
            status_code=401,
        )

    resp = RedirectResponse("/admin/dashboard", status_code=302)
    cookie = sign_dict({"admin": True}, settings.APP_SECRET, ttl_seconds=60 * 60 * 12)
    resp.set_cookie(
        "admin_session",
        cookie,
        httponly=True,
        samesite="lax",
        secure=settings.PUBLIC_BASE_URL.startswith("https://"),
        max_age=60 * 60 * 12,
    )
    return resp


@router.post("/admin/logout")
def admin_logout() -> RedirectResponse:
    resp = RedirectResponse("/admin", status_code=302)
    resp.delete_cookie("admin_session")
    return resp


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request) -> HTMLResponse:
    if not _is_admin(request):
        return RedirectResponse("/admin", status_code=302)

    db: Db = request.app.state.db
    stats = db.stats()
    logs = db.recent_logs(limit=200)
    revenue_chf = (stats.get("revenue_chf_centimes", 0) or 0) / 100.0

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "stats": stats,
            "revenue_chf": revenue_chf,
            "logs": logs,
            "now": int(time.time()),
        },
    )

