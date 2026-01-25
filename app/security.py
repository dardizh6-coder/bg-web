from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64u_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def sign_dict(payload: dict[str, Any], secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    body = {"iat": now, "exp": now + ttl_seconds, "p": payload}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return f"{_b64u_encode(raw)}.{_b64u_encode(sig)}"


def verify_signed_dict(token: str, secret: str) -> dict[str, Any] | None:
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _b64u_decode(raw_b64)
        sig = _b64u_decode(sig_b64)
        expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        body = json.loads(raw.decode("utf-8"))
        if int(body.get("exp", 0)) < int(time.time()):
            return None
        return body.get("p") or None
    except Exception:
        return None

