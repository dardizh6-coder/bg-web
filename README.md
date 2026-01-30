# Car Photo Processor (Background Removal + Dealership Backgrounds)

Production-ready, web-based car photo processing app:
- Batch upload (mobile camera + drag/drop)
- Local AI background removal (no third-party image processing APIs)
- Editor (rotate/position/scale) with live preview
- Server-side high-res render (optional shadow) + watermark for free users
- Stripe one-time payment (1.99 CHF) to remove watermark + hide ads
- Simple admin dashboard (SQLite stats + logs)

## Quick start (local)

Create a virtualenv, then:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

## Environment

Copy `.env.example` → `.env` and set:
- `APP_SECRET` (required)
- `ADMIN_PASSWORD` (required for `/admin`)
- Stripe vars if enabling payments

## Notes

- The background removal model is loaded lazily on first use and reused.
- First run may download model weights locally (still “local processing”, no API calls).
- Backgrounds are loaded from the `images/` folder (if present).

## Deploy (Railway)

- Use the included `Dockerfile`
- Set the env vars in Railway:
  - **Required:** `APP_SECRET`, `ADMIN_PASSWORD`, `PUBLIC_BASE_URL` (e.g. `https://zhaku.eu` or your Railway URL)
  - **CORS:** If frontend is on another domain, set `CORS_ORIGINS=https://zhaku.eu,https://www.zhaku.eu` or `CORS_ORIGINS=*` to allow any origin
  - **Optional API_KEY:** Set `API_KEY=your-secret`; then in the frontend set `window.API_BASE_URL` to your Railway URL and `window.API_KEY` to the same value. All requests will use `Authorization: Bearer <API_KEY>` and no client registration is needed.
