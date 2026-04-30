from __future__ import annotations

import tkinter as tk
from pathlib import Path

from desktop_integration import configure_window_icon
from ui_app import PhotoAnalyzerApp
from window_layout import center_window


def open_single_image_window(master: tk.Misc, image_path: str | Path | None = None) -> PhotoAnalyzerApp:
    window = tk.Toplevel(master.winfo_toplevel())
    window.title("单张图片分析模式")
    configure_window_icon(window)
    app = PhotoAnalyzerApp(window, single_mode=True)
    center_window(window, 1780, 1080)
    if image_path is not None:
        app.load_single_image(Path(image_path))
    return app
