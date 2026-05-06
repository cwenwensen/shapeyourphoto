from __future__ import annotations

from dataclasses import dataclass
import time
import tkinter as tk
from tkinter import ttk

from window_layout import center_window


@dataclass
class TaskProgressState:
    total: int = 1
    done: float = 0.0
    title: str = "待处理"
    detail: str = "尚未开始。"
    status: str = "尚未开始。"
    dialog_title: str = "任务进度"
    dialog_header: str = "正在处理任务"
    accent: str = "#5d8f73"
    started_at: float = 0.0
    elapsed_text: str = "耗时 00:00"


class TaskProgressDialog:
    def __init__(
        self,
        master: tk.Misc,
        state: TaskProgressState,
        *,
        cancel_callback=None,
        cancel_text: str = "取消",
    ) -> None:
        self._cancel_callback = cancel_callback
        self._tick_after_id: str | None = None
        self._started_at = state.started_at or time.monotonic()
        self.window = tk.Toplevel(master)
        self.window.title(state.dialog_title)
        self.window.transient(master.winfo_toplevel())
        self.window.resizable(False, False)
        self.window.geometry("560x260")
        self.window.minsize(520, 240)
        self.window.configure(bg="#edf4ef")
        self.window.protocol("WM_DELETE_WINDOW", self._handle_close)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.title_var = tk.StringVar(value=state.dialog_header)
        self.detail_var = tk.StringVar(value="准备中...")
        self.count_var = tk.StringVar(value="0 / 0")
        self.elapsed_var = tk.StringVar(value=state.elapsed_text)

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

        stat_row = ttk.Frame(outer, style="Panel.TFrame")
        stat_row.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        stat_row.columnconfigure(0, weight=1)
        ttk.Label(stat_row, textvariable=self.count_var, style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(stat_row, textvariable=self.elapsed_var, style="PanelTitle.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(outer, textvariable=self.detail_var, wraplength=500).grid(row=4, column=0, sticky="w", pady=(6, 0))

        self.accent_line = tk.Frame(outer, bg=state.accent, height=4)
        self.accent_line.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        if cancel_callback is not None:
            ttk.Button(outer, text=cancel_text, command=self._handle_cancel).grid(row=6, column=0, sticky="e", pady=(12, 0))

        self.window.update_idletasks()
        center_window(self.window, 560, 260)
        self.update_state(state)
        self._schedule_elapsed_tick()
        self.window.lift()

    def _handle_close(self) -> None:
        if self._cancel_callback is not None:
            self._handle_cancel()

    def _handle_cancel(self) -> None:
        if self._cancel_callback is not None:
            self._cancel_callback()

    def _schedule_elapsed_tick(self) -> None:
        if self.window.winfo_exists():
            self._tick_after_id = self.window.after(1000, self._tick_elapsed)

    def _tick_elapsed(self) -> None:
        if not self.window.winfo_exists():
            return
        self.elapsed_var.set(_format_elapsed(time.monotonic() - self._started_at))
        self._schedule_elapsed_tick()

    def update_state(self, state: TaskProgressState) -> None:
        self._started_at = state.started_at or self._started_at
        maximum = max(1, state.total)
        self.window.title(state.dialog_title)
        self.progressbar.configure(maximum=maximum)
        self.progress_var.set(float(state.done))
        if float(state.done).is_integer():
            done_text = str(int(state.done))
        else:
            done_text = f"{state.done:.1f}"
        self.count_var.set(f"{done_text} / {state.total}")
        self.title_var.set(state.dialog_header)
        self.detail_var.set(state.detail)
        self.elapsed_var.set(_format_elapsed(time.monotonic() - self._started_at))
        self.accent_line.configure(bg=state.accent)
        self.window.update_idletasks()

    def close(self) -> None:
        if self.window.winfo_exists():
            if self._tick_after_id is not None:
                try:
                    self.window.after_cancel(self._tick_after_id)
                except tk.TclError:
                    pass
                self._tick_after_id = None
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
        self._cancel_callback = None
        self._cancel_text = "取消"

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
        cancel_callback=None,
        cancel_text: str = "取消",
    ) -> None:
        started_at = time.monotonic()
        self.state = TaskProgressState(
            total=max(1, total),
            done=0,
            title=title,
            detail=detail,
            status=status or detail,
            dialog_title=dialog_title or title,
            dialog_header=dialog_header or title,
            accent=accent or self.state.accent,
            started_at=started_at,
            elapsed_text=_format_elapsed(0.0),
        )
        self._cancel_callback = cancel_callback
        self._cancel_text = cancel_text
        self._sync_main()
        if show_dialog:
            self._ensure_dialog()
        else:
            self.close_dialog()
        self._sync_dialog()

    def update(
        self,
        *,
        done: float,
        total: int | None = None,
        title: str | None = None,
        detail: str | None = None,
        status: str | None = None,
        dialog_title: str | None = None,
        dialog_header: str | None = None,
    ) -> None:
        if total is not None:
            self.state.total = max(1, total)
        self.state.done = max(0.0, min(float(done), float(self.state.total)))
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
        if self.state.started_at:
            self.state.elapsed_text = _format_elapsed(time.monotonic() - self.state.started_at)
        self._sync_main()
        self._sync_dialog()

    def finish(self, *, title: str, detail: str, status: str | None = None, close_dialog: bool = True) -> None:
        self.state.done = self.state.total
        self.state.title = title
        self.state.detail = detail
        self.state.status = status or detail
        if self.state.started_at:
            self.state.elapsed_text = _format_elapsed(time.monotonic() - self.state.started_at)
        self._sync_main()
        self._sync_dialog()
        if close_dialog:
            self.close_dialog()

    def close_dialog(self) -> None:
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None
        self._cancel_callback = None

    def _ensure_dialog(self) -> None:
        if self.dialog is None:
            self.dialog = TaskProgressDialog(
                self.master,
                self.state,
                cancel_callback=self._cancel_callback,
                cancel_text=self._cancel_text,
            )
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


def _format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"耗时 {hours:02d}:{minutes:02d}:{sec:02d}"
    return f"耗时 {minutes:02d}:{sec:02d}"
