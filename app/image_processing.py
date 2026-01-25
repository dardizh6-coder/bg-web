from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except Exception:
        return ImageFont.load_default()


def apply_soft_shadow(bg_rgba: Image.Image, car_rgba: Image.Image, pos_xy: tuple[int, int], opacity: float = 0.28) -> None:
    """
    Draw a subtle ground shadow *behind* the car on the background.
    pos_xy is the top-left position where car_rgba will be pasted later.
    """
    if bg_rgba.mode != "RGBA" or car_rgba.mode != "RGBA":
        raise ValueError("Expected RGBA images")

    alpha = car_rgba.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        return

    x0, y0, x1, y1 = bbox
    car_w = x1 - x0
    car_h = y1 - y0

    # Shadow ellipse roughly under car footprint.
    shadow = Image.new("RGBA", bg_rgba.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    ell_w = int(car_w * 0.72)
    ell_h = max(12, int(car_h * 0.10))

    # Place slightly below the car (relative to its bbox), then map into background coords.
    cx = pos_xy[0] + x0 + car_w // 2
    cy = pos_xy[1] + y0 + int(car_h * 0.92)

    left = cx - ell_w // 2
    top = cy - ell_h // 2
    right = cx + ell_w // 2
    bottom = cy + ell_h // 2

    a = int(255 * max(0.0, min(1.0, opacity)))
    d.ellipse((left, top, right, bottom), fill=(0, 0, 0, a))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(8, ell_h * 0.65)))
    bg_rgba.alpha_composite(shadow)


def _make_watermark_layer(size: tuple[int, int], text: str, angle_deg: float, opacity: float) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Scale watermark size to image dimensions.
    base = max(w, h)
    font_size = max(14, int(base * 0.035))
    f = _font(font_size)

    step = int(font_size * 4.2)
    # Brand-blue watermark (more noticeable than before, still subtle)
    fill = (29, 78, 216, int(255 * max(0.0, min(1.0, opacity))))

    for y in range(-step, h + step, step):
        for x in range(-step, w + step, step):
            d.text((x, y), text, font=f, fill=fill)
            # tiny offset pass for readability on very bright panels
            d.text((x + 1, y + 1), text, font=f, fill=(29, 78, 216, int(fill[3] * 0.65)))

    if angle_deg:
        layer = layer.rotate(angle_deg, resample=Image.Resampling.BICUBIC, expand=False)

    return layer


def apply_watermark_on_car(car_rgba: Image.Image, angle_deg: float, text: str = "aucto.ch") -> Image.Image:
    """
    Repeated subtle watermark, clipped to the car alpha mask.
    Angle aligned with car orientation (angle_deg).
    """
    if car_rgba.mode != "RGBA":
        car_rgba = car_rgba.convert("RGBA")

    w, h = car_rgba.size
    alpha = car_rgba.split()[-1]
    if not alpha.getbbox():
        return car_rgba

    wm = _make_watermark_layer((w, h), text=text, angle_deg=angle_deg, opacity=0.16)
    # Clip watermark to car region only.
    wm.putalpha(ImageChops.multiply(wm.split()[-1], alpha))
    out = car_rgba.copy()
    out.alpha_composite(wm)
    return out


@dataclass
class RenderParams:
    rotate_deg: float = 0.0
    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    shadow: bool = True
    snap_center: bool = False


def render_composite(
    cutout_rgba: Image.Image,
    background_rgb: Image.Image,
    params: RenderParams,
    paid: bool,
    watermark_text: str = "aucto.ch",
) -> Image.Image:
    """
    Produces an RGBA composite at the cutout's native resolution.
    """
    if cutout_rgba.mode != "RGBA":
        cutout_rgba = cutout_rgba.convert("RGBA")

    w, h = cutout_rgba.size
    if background_rgb.size != (w, h):
        background_rgb = background_rgb.resize((w, h), resample=Image.Resampling.LANCZOS)

    bg = background_rgb.convert("RGBA")

    # Apply watermark to the car only (free users).
    car = cutout_rgba
    if not paid:
        car = apply_watermark_on_car(car, angle_deg=params.rotate_deg, text=watermark_text)

    # Scale
    scale = max(0.5, min(2.0, float(params.scale)))
    if abs(scale - 1.0) > 1e-4:
        car = car.resize((int(w * scale), int(h * scale)), resample=Image.Resampling.LANCZOS)

    # Rotate around center (expand to preserve content).
    rotate = float(params.rotate_deg or 0.0)
    if abs(rotate) > 1e-3:
        car = car.rotate(rotate, resample=Image.Resampling.BICUBIC, expand=True)

    cw, ch = car.size
    ox = 0.0 if params.snap_center else float(params.offset_x or 0.0)
    oy = 0.0 if params.snap_center else float(params.offset_y or 0.0)

    x = int((w - cw) / 2 + ox)
    y = int((h - ch) / 2 + oy)

    if params.shadow:
        apply_soft_shadow(bg, car, (x, y), opacity=0.26)

    bg.alpha_composite(car, dest=(x, y))
    return bg


def encode_image(img: Image.Image, fmt: str, quality: int = 92) -> bytes:
    fmt = fmt.lower().strip(".")
    bio = io.BytesIO()
    if fmt in ("jpg", "jpeg"):
        rgb = img.convert("RGB")
        rgb.save(bio, format="JPEG", quality=quality, optimize=True, progressive=True)
    elif fmt == "png":
        img.save(bio, format="PNG", optimize=True)
    else:
        raise ValueError("Unsupported output format")
    return bio.getvalue()


def clamp_preview(img: Image.Image, max_dim: int = 1200) -> Image.Image:
    w, h = img.size
    m = max(w, h)
    if m <= max_dim:
        return img
    s = max_dim / m
    return img.resize((int(w * s), int(h * s)), resample=Image.Resampling.LANCZOS)

