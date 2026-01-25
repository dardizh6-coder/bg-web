from __future__ import annotations

import io
import threading
import traceback
from pathlib import Path
from typing import Callable

from PIL import Image
from rembg import new_session, remove

from app.config import settings

_session_lock = threading.Lock()
_session: object | None = None
_session_model: str | None = None


def _get_session() -> object:
    """Create (and reuse) a rembg session lazily.

    On small containers, loading/downloading the model at startup can get the process killed.
    """
    global _session, _session_model
    if _session is not None and _session_model == settings.RMBG_MODEL:
        return _session
    with _session_lock:
        if _session is None or _session_model != settings.RMBG_MODEL:
            _session = new_session(settings.RMBG_MODEL)
            _session_model = settings.RMBG_MODEL
        return _session


def remove_background_to_file(
    *,
    original_path: Path,
    cutout_path: Path,
    session: object | None,
    on_error: Callable[[str], None],
    on_success: Callable[[int, int], None],
) -> None:
    try:
        if session is None:
            session = _get_session()
        raw = original_path.read_bytes()
        out = remove(raw, session=session)  # returns PNG bytes with alpha
        cutout_path.parent.mkdir(parents=True, exist_ok=True)
        cutout_path.write_bytes(out)

        with Image.open(io.BytesIO(out)) as im:
            im = im.convert("RGBA")
            on_success(im.width, im.height)
    except Exception as e:
        detail = f"{e}\n{traceback.format_exc(limit=6)}"
        on_error(detail)

