from __future__ import annotations

import os

try:
    # Allows local dev via a .env file. Environment variables still win.
    from dotenv import load_dotenv

    load_dotenv(override=False)
except Exception:
    pass


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v


class Settings:
    def __init__(self) -> None:
        self.APP_ENV: str = _env("APP_ENV", "development") or "development"
        self.PUBLIC_BASE_URL: str = _env("PUBLIC_BASE_URL", "http://localhost:8000") or "http://localhost:8000"

        self.APP_SECRET: str = _env("APP_SECRET", "") or ""
        self.ADMIN_PASSWORD: str = _env("ADMIN_PASSWORD", "") or ""

        # Dev-friendly defaults (still require real values in production).
        if self.APP_ENV == "development":
            if not self.APP_SECRET:
                self.APP_SECRET = "devsecret"
            if not self.ADMIN_PASSWORD:
                self.ADMIN_PASSWORD = "devpass"

        self.STRIPE_SECRET_KEY: str = _env("STRIPE_SECRET_KEY", "") or ""
        self.STRIPE_WEBHOOK_SECRET: str = _env("STRIPE_WEBHOOK_SECRET", "") or ""
        self.STRIPE_PRICE_CHF_199: str = _env("STRIPE_PRICE_CHF_199", "") or ""

        self.ADSENSE_CLIENT: str = _env("ADSENSE_CLIENT", "") or ""
        self.ADSENSE_SLOT: str = _env("ADSENSE_SLOT", "") or ""

        self.DATA_DIR: str = _env("DATA_DIR", "data") or "data"
        self.RMBG_MODEL: str = _env("RMBG_MODEL", "u2net") or "u2net"


settings = Settings()

