from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from window_layout import center_window


class RepairCompletionDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Widget,
        *,
        title: str,
        summary_lines: list[str],
        detail_lines: list[str],
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.resizable(True, True)
        self.minsize(760, 520)

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        summary_frame = ttk.LabelFrame(outer, text="摘要", padding=10)
        summary_frame.grid(row=0, column=0, sticky="ew")
        for line in summary_lines:
            ttk.Label(summary_frame, text=line, anchor="w").pack(fill="x")

        detail_frame = ttk.LabelFrame(outer, text="详情", padding=10)
        detail_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)

        self.text = tk.Text(
            detail_frame,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            bg="#fbfcfa",
            relief="flat",
            padx=10,
            pady=10,
        )
        scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.insert("1.0", "\n".join(detail_lines) if detail_lines else "本轮没有额外详情。")
        self.text.config(state="disabled")

        button_row = ttk.Frame(outer)
        button_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(button_row, text="复制详情", command=self._copy).pack(side="left")
        ttk.Button(button_row, text="关闭", command=self.destroy).pack(side="right")

        center_window(self, 920, 680)

    def _copy(self) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(self.text.get("1.0", "end-1c"))
        except Exception:
            pass


def show_repair_completion_dialog(
    parent: tk.Widget,
    *,
    title: str,
    summary_lines: list[str],
    detail_lines: list[str],
) -> None:
    dialog = RepairCompletionDialog(parent, title=title, summary_lines=summary_lines, detail_lines=detail_lines)
    dialog.wait_window()
