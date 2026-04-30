from __future__ import annotations

import ctypes
from pathlib import Path

from PIL import Image, ImageDraw

from app_metadata import APP_ID


def _icon_paths() -> tuple[Path, Path]:
    assets_dir = Path(__file__).resolve().parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir / "app_icon.png", assets_dir / "app_icon.ico"


def ensure_app_icon() -> tuple[Path, Path]:
    png_path, ico_path = _icon_paths()
    if png_path.exists() and ico_path.exists():
        return png_path, ico_path

    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle((20, 20, 236, 236), radius=56, fill=(28, 58, 48, 255))
    draw.ellipse((56, 56, 200, 200), fill=(236, 247, 236, 255))
    draw.ellipse((82, 82, 174, 174), fill=(28, 58, 48, 255))
    draw.polygon([(182, 174), (228, 220), (214, 234), (166, 188)], fill=(246, 198, 91, 255))
    draw.rectangle((48, 178, 128, 196), fill=(246, 198, 91, 255))
    draw.rectangle((48, 156, 106, 170), fill=(244, 120, 76, 255))

    canvas.save(png_path)
    canvas.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return png_path, ico_path


def configure_window_icon(root) -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    png_path, ico_path = ensure_app_icon()
    try:
        icon = ctypes.windll.user32.LoadImageW(0, str(ico_path), 1, 0, 0, 0x00000010)
        if icon:
            ctypes.windll.user32.SendMessageW(root.winfo_id(), 0x0080, 0, icon)
            ctypes.windll.user32.SendMessageW(root.winfo_id(), 0x0080, 1, icon)
    except Exception:
        pass

    try:
        root.iconbitmap(default=str(ico_path))
    except Exception:
        pass

    try:
        from tkinter import PhotoImage

        root._app_icon = PhotoImage(file=str(png_path))
        root.iconphoto(True, root._app_icon)
    except Exception:
        pass
