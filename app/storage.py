from __future__ import annotations

import re
from pathlib import Path

from app.config import settings


def data_dir() -> Path:
    return Path(settings.DATA_DIR)


def db_path() -> Path:
    return data_dir() / "app.db"


def originals_dir() -> Path:
    return data_dir() / "original"


def cutouts_dir() -> Path:
    return data_dir() / "cutout"


def safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return name[:120] or "upload"


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    originals_dir().mkdir(parents=True, exist_ok=True)
    cutouts_dir().mkdir(parents=True, exist_ok=True)

