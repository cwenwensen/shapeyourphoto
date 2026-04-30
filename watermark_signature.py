from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SOFTWARE_NAME = "ShapeYourPhoto"
AUTHOR_NAME = "Helloalp"


def _load_overlay_font(image: Image.Image) -> ImageFont.ImageFont:
    font_size = max(14, int(min(image.size) * 0.018))
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), font_size)
            except OSError:
                continue
    return ImageFont.load_default()


def add_signature_overlay(image: Image.Image, text: str | None = None) -> Image.Image:
    signed = image.copy()
    draw = ImageDraw.Draw(signed, "RGBA")
    font = _load_overlay_font(signed)
    overlay_text = text or f"{SOFTWARE_NAME} | {AUTHOR_NAME}"
    bbox = draw.textbbox((0, 0), overlay_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    margin = max(16, int(min(signed.size) * 0.02))
    x0 = signed.width - text_w - margin * 2
    y0 = signed.height - text_h - margin * 2
    draw.rounded_rectangle((x0, y0, signed.width - margin, signed.height - margin), radius=10, fill=(18, 30, 24, 145))
    draw.text((x0 + margin // 2, y0 + margin // 2), overlay_text, font=font, fill=(245, 251, 246, 230))
    return signed
