from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont


@dataclass(frozen=True)
class BackgroundDef:
    id: str
    name: str
    description: str


BACKGROUNDS: list[BackgroundDef] = [
    BackgroundDef(
        id="studio_neutral",
        name="Neutral studio",
        description="Soft studio lighting with neutral floor.",
    ),
    BackgroundDef(
        id="outdoor_lot",
        name="Outdoor lot",
        description="Simple sky + asphalt lot gradient.",
    ),
    BackgroundDef(
        id="branded_wall",
        name="Branded wall",
        description="Clean wall with subtle brand pattern.",
    ),
    BackgroundDef(
        id="gradient_silver",
        name="Silver gradient",
        description="Modern silver/gray gradient background.",
    ),
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # PIL default font is fine for server-side generated backgrounds.
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except Exception:
        return ImageFont.load_default()


def _linear_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(h - 1, 1)
        col = (
            int(top[0] * (1 - t) + bottom[0] * t),
            int(top[1] * (1 - t) + bottom[1] * t),
            int(top[2] * (1 - t) + bottom[2] * t),
        )
        draw.line([(0, y), (w, y)], fill=col)
    return base


def _radial_glow(size: tuple[int, int], center: tuple[int, int], inner: int, outer: int) -> Image.Image:
    w, h = size
    glow = Image.new("L", size, color=0)
    draw = ImageDraw.Draw(glow)
    # Oversized ellipse for a soft vignette/glow.
    r = max(w, h)
    draw.ellipse((center[0] - r, center[1] - r, center[0] + r, center[1] + r), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(w, h) / 6))
    # Normalize levels roughly
    return glow


def generate_background(bg_id: str, size: tuple[int, int]) -> Image.Image:
    w, h = size
    if w <= 0 or h <= 0:
        raise ValueError("Invalid background size")

    if bg_id == "studio_neutral":
        sky = _linear_gradient(size, (245, 245, 246), (220, 220, 222))
        floor_h = int(h * 0.22)
        floor = _linear_gradient((w, floor_h), (210, 210, 212), (175, 175, 178))
        img = sky
        img.paste(floor, (0, h - floor_h))
        # soft vignette
        vign = _radial_glow(size, (w // 2, int(h * 0.35)), inner=240, outer=0)
        vign = vign.point(lambda p: int(p * 0.18))
        img = Image.composite(Image.new("RGB", size, (0, 0, 0)), img, Image.eval(vign, lambda p: 255 - p))
        return img

    if bg_id == "outdoor_lot":
        sky_h = int(h * 0.58)
        sky = _linear_gradient((w, sky_h), (190, 215, 235), (230, 240, 248))
        ground = _linear_gradient((w, h - sky_h), (90, 92, 96), (55, 56, 60))
        img = Image.new("RGB", size, (0, 0, 0))
        img.paste(sky, (0, 0))
        img.paste(ground, (0, sky_h))
        # subtle horizon glow
        glow = Image.new("RGBA", size, (255, 255, 255, 0))
        gdraw = ImageDraw.Draw(glow)
        gdraw.rectangle((0, sky_h - 30, w, sky_h + 40), fill=(255, 255, 255, 24))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=18))
        return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    if bg_id == "branded_wall":
        base = _linear_gradient(size, (244, 244, 245), (228, 228, 230))
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        step = max(140, min(w, h) // 6)
        txt = "aucto.ch"
        f = _font(max(16, step // 6))
        for y in range(-step, h + step, step):
            for x in range(-step, w + step, step):
                d.text((x, y), txt, fill=(20, 20, 22, 18), font=f)
        overlay = overlay.rotate(-18, resample=Image.Resampling.BICUBIC, expand=False)
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.6))
        return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

    if bg_id == "gradient_silver":
        return _linear_gradient(size, (250, 250, 252), (196, 198, 202))

    raise KeyError(f"Unknown background '{bg_id}'")

