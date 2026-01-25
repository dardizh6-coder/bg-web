from __future__ import annotations

import io
import traceback
from pathlib import Path
from typing import Callable

from PIL import Image
from rembg import remove


def remove_background_to_file(
    *,
    original_path: Path,
    cutout_path: Path,
    session: object,
    on_error: Callable[[str], None],
    on_success: Callable[[int, int], None],
) -> None:
    try:
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

