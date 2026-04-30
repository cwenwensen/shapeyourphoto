from __future__ import annotations

import tkinter as tk

from app_metadata import APP_NAME, APP_VERSION
from desktop_integration import configure_window_icon
from ui_app import PhotoAnalyzerApp
from window_layout import center_window


def main() -> None:
    root = tk.Tk()
    root.title(f"{APP_NAME} v{APP_VERSION}")
    configure_window_icon(root)
    PhotoAnalyzerApp(root)
    center_window(root, 1700, 1020)
    root.mainloop()


if __name__ == "__main__":
    main()
