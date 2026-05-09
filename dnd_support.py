"""跨平台文件拖拽分派。

Windows: 复用 drag_drop.WindowsFileDropTarget 的原生 ctypes 实现，行为/性能不变。
macOS / Linux: 使用 tkinterdnd2，要求根窗口由 TkinterDnD.Tk() 创建（见 app.py）。

对外只暴露：
- create_root() —— 按平台返回正确的 Tk 根实例
- install_drop_target(root, callback) —— 在主窗口安装拖拽接收器
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Callable, Iterable


def create_root() -> tk.Tk:
    """按平台创建根窗口。"""
    if sys.platform != "win32":
        try:
            from tkinterdnd2 import TkinterDnD

            return TkinterDnD.Tk()
        except Exception:
            # tkinterdnd2 不可用时退回普通 Tk，拖拽功能在该平台禁用，但应用仍可启动
            pass
    return tk.Tk()


def _parse_tkdnd_data(data: str) -> list[Path]:
    """tkinterdnd2 的 event.data 是 Tcl 列表字符串，含空格的路径用 {} 包围。"""
    paths: list[Path] = []
    buf: list[str] = []
    in_brace = False
    for ch in data:
        if ch == "{" and not buf:
            in_brace = True
            continue
        if ch == "}" and in_brace:
            paths.append(Path("".join(buf)))
            buf = []
            in_brace = False
            continue
        if ch == " " and not in_brace:
            if buf:
                paths.append(Path("".join(buf)))
                buf = []
            continue
        buf.append(ch)
    if buf:
        paths.append(Path("".join(buf)))
    return paths


class _NoopDropTarget:
    """tkinterdnd2 不可用时的占位实现，保证调用方不报错。"""

    def install(self) -> None:
        return None

    def uninstall(self) -> None:
        return None


class _Tkdnd2DropTarget:
    """基于 tkinterdnd2 的跨平台拖拽接收器。"""

    def __init__(self, window: tk.Misc, callback: Callable[[Iterable[Path]], None]) -> None:
        self.window = window
        self.callback = callback
        self._installed = False

    def install(self) -> None:
        try:
            from tkinterdnd2 import DND_FILES
        except Exception:
            return
        try:
            self.window.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            self.window.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            self._installed = True
        except Exception:
            self._installed = False

    def uninstall(self) -> None:
        if not self._installed:
            return
        try:
            self.window.drop_target_unregister()  # type: ignore[attr-defined]
        except Exception:
            pass
        self._installed = False

    def _on_drop(self, event) -> None:
        try:
            paths = _parse_tkdnd_data(str(event.data))
        except Exception:
            paths = []
        if paths:
            self.window.after(0, lambda p=paths: self.callback(p))


def install_drop_target(root: tk.Misc, callback: Callable[[Iterable[Path]], None]):
    """根据平台返回已就绪的拖拽接收器（已调用 install）。"""
    if sys.platform == "win32":
        from drag_drop import WindowsFileDropTarget

        target = WindowsFileDropTarget(root, callback)
    else:
        target = _Tkdnd2DropTarget(root, callback)

    try:
        target.install()
    except Exception:
        return _NoopDropTarget()
    return target
