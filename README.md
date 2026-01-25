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

- The background removal model is loaded once on startup and reused.
- First run may download model weights locally (still “local processing”, no API calls).

## Deploy (Railway)

- Use the included `Dockerfile`
- Set the env vars in Railway
