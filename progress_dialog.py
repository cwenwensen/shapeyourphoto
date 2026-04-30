from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

from window_layout import center_window


@dataclass
class TaskProgressState:
    total: int = 1
    done: int = 0
    title: str = "待处理"
    detail: str = "尚未开始。"
    status: str = "尚未开始。"
    dialog_title: str = "任务进度"
    dialog_header: str = "正在处理任务"
    accent: str = "#5d8f73"


class TaskProgressDialog:
    def __init__(self, master: tk.Misc, state: TaskProgressState) -> None:
        self.window = tk.Toplevel(master)
        self.window.title(state.dialog_title)
        self.window.transient(master.winfo_toplevel())
        self.window.resizable(False, False)
        self.window.geometry("560x220")
        self.window.minsize(520, 210)
        self.window.configure(bg="#edf4ef")
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.title_var = tk.StringVar(value=state.dialog_header)
        self.detail_var = tk.StringVar(value="准备中...")
        self.count_var = tk.StringVar(value="0 / 0")

        outer = ttk.Frame(self.window, padding=18, style="Panel.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, textvariable=self.title_var, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="当前任务会持续刷新真实进度，完成后自动关闭。",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        progress_shell = tk.Frame(outer, bg="#d9e6dd", height=22)
        progress_shell.grid(row=2, column=0, sticky="ew")
        progress_shell.grid_columnconfigure(0, weight=1)
        self.progressbar = ttk.Progressbar(progress_shell, mode="determinate", maximum=1, variable=self.progress_var)
        self.progressbar.grid(row=0, column=0, sticky="ew")

        ttk.Label(outer, textvariable=self.count_var, style="PanelTitle.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Label(outer, textvariable=self.detail_var, wraplength=500).grid(row=4, column=0, sticky="w", pady=(6, 0))

        self.accent_line = tk.Frame(outer, bg=state.accent, height=4)
        self.accent_line.grid(row=5, column=0, sticky="ew", pady=(14, 0))

        self.window.update_idletasks()
        center_window(self.window, 560, 220)
        self.update_state(state)
        self.window.lift()

    def update_state(self, state: TaskProgressState) -> None:
        maximum = max(1, state.total)
        self.window.title(state.dialog_title)
        self.progressbar.configure(maximum=maximum)
        self.progress_var.set(float(state.done))
        self.count_var.set(f"{state.done} / {state.total}")
        self.title_var.set(state.dialog_header)
        self.detail_var.set(state.detail)
        self.accent_line.configure(bg=state.accent)
        self.window.update_idletasks()

    def close(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()


class TaskProgressController:
    def __init__(
        self,
        master: tk.Misc,
        progress_bar: ttk.Progressbar,
        progress_var: tk.DoubleVar,
        title_var: tk.StringVar,
        detail_var: tk.StringVar,
        status_var: tk.StringVar,
    ) -> None:
        self.master = master
        self.progress_bar = progress_bar
        self.progress_var = progress_var
        self.title_var = title_var
        self.detail_var = detail_var
        self.status_var = status_var
        self.state = TaskProgressState()
        self.dialog: TaskProgressDialog | None = None

    def begin(
        self,
        *,
        total: int,
        title: str,
        detail: str,
        status: str | None = None,
        show_dialog: bool = False,
        dialog_title: str | None = None,
        dialog_header: str | None = None,
        accent: str | None = None,
    ) -> None:
        self.state = TaskProgressState(
            total=max(1, total),
            done=0,
            title=title,
            detail=detail,
            status=status or detail,
            dialog_title=dialog_title or title,
            dialog_header=dialog_header or title,
            accent=accent or self.state.accent,
        )
        self._sync_main()
        if show_dialog:
            self._ensure_dialog()
        else:
            self.close_dialog()
        self._sync_dialog()

    def update(
        self,
        *,
        done: int,
        total: int | None = None,
        title: str | None = None,
        detail: str | None = None,
        status: str | None = None,
        dialog_title: str | None = None,
        dialog_header: str | None = None,
    ) -> None:
        if total is not None:
            self.state.total = max(1, total)
        self.state.done = max(0, min(done, self.state.total))
        if title is not None:
            self.state.title = title
        if detail is not None:
            self.state.detail = detail
        if status is not None:
            self.state.status = status
        if dialog_title is not None:
            self.state.dialog_title = dialog_title
        if dialog_header is not None:
            self.state.dialog_header = dialog_header
        self._sync_main()
        self._sync_dialog()

    def finish(self, *, title: str, detail: str, status: str | None = None, close_dialog: bool = True) -> None:
        self.state.done = self.state.total
        self.state.title = title
        self.state.detail = detail
        self.state.status = status or detail
        self._sync_main()
        self._sync_dialog()
        if close_dialog:
            self.close_dialog()

    def close_dialog(self) -> None:
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

    def _ensure_dialog(self) -> None:
        if self.dialog is None:
            self.dialog = TaskProgressDialog(self.master, self.state)
        else:
            self.dialog.window.lift()

    def _sync_main(self) -> None:
        self.progress_bar.configure(maximum=max(1, self.state.total))
        self.progress_var.set(float(self.state.done))
        self.title_var.set(self.state.title)
        self.detail_var.set(self.state.detail)
        self.status_var.set(self.state.status)

    def _sync_dialog(self) -> None:
        if self.dialog is not None:
            self.dialog.update_state(self.state)
