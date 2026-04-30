from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import tkinter as tk


WM_DROPFILES = 0x0233
GWL_WNDPROC = -4


def _iter_drop_files(hdrop) -> list[Path]:
    shell32 = ctypes.windll.shell32
    count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
    results: list[Path] = []
    for index in range(count):
        length = shell32.DragQueryFileW(hdrop, index, None, 0) + 1
        buffer = ctypes.create_unicode_buffer(length)
        shell32.DragQueryFileW(hdrop, index, buffer, length)
        results.append(Path(buffer.value))
    shell32.DragFinish(hdrop)
    return results


class WindowsFileDropTarget:
    def __init__(self, window: tk.Misc, callback) -> None:
        self.window = window
        self.callback = callback
        self.hwnd: int | None = None
        self._old_proc = None
        self._new_proc = None

    def install(self) -> None:
        if not hasattr(ctypes, "WINFUNCTYPE"):
            return
        self.window.update_idletasks()
        self.hwnd = self.window.winfo_id()
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        WNDPROC = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        @WNDPROC
        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                dropped = _iter_drop_files(wparam)
                self.window.after(0, lambda files=dropped: self.callback(files))
                return 0
            return user32.CallWindowProcW(self._old_proc, hwnd, msg, wparam, lparam)

        self._new_proc = _wnd_proc
        self._old_proc = user32.SetWindowLongPtrW(self.hwnd, GWL_WNDPROC, _wnd_proc)
        shell32.DragAcceptFiles(self.hwnd, True)

    def uninstall(self) -> None:
        if self.hwnd is None or self._old_proc is None:
            return
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        shell32.DragAcceptFiles(self.hwnd, False)
        user32.SetWindowLongPtrW(self.hwnd, GWL_WNDPROC, self._old_proc)
        self._old_proc = None
        self._new_proc = None
