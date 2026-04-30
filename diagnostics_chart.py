from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from models import AnalysisResult


class DiagnosticsChart(ttk.Frame):
    def __init__(self, master) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg="#f8fbf8", highlightthickness=0, height=280)
        self.v_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.h_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll.grid(row=1, column=0, sticky="ew")
        self.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Configure>", self._on_resize)
        self._result: AnalysisResult | None = None

    def update_result(self, result: AnalysisResult | None) -> None:
        self._result = result
        self._draw()

    def _on_resize(self, _event=None) -> None:
        self._draw()

    def _draw(self) -> None:
        self.canvas.delete("all")
        width = max(520, self.canvas.winfo_width() or 520)
        self.canvas.configure(scrollregion=(0, 0, width, 300))

        if self._result is None:
            self.canvas.create_text(18, 18, anchor="nw", text="完成分析后，这里会显示风险与关键指标条图。", fill="#476051", font=("Microsoft YaHei UI", 10))
            return

        x0 = 20
        y = 16
        bar_w = max(220, width - 220)

        self.canvas.create_text(x0, y, anchor="nw", text="问题强度", fill="#1c3c2a", font=("Microsoft YaHei UI", 10, "bold"))
        y += 28

        issue_rows = self._result.issues[:6] or []
        if not issue_rows:
            self.canvas.create_text(x0, y, anchor="nw", text="当前未检测到明显问题。", fill="#4c6a57", font=("Microsoft YaHei UI", 10))
            y += 28
        else:
            for issue in issue_rows:
                y = self._draw_bar(y, issue.label, issue.score, f"{issue.score:.2f}", "#d35b42", bar_w)

        y += 10
        self.canvas.create_text(x0, y, anchor="nw", text="关键指标", fill="#1c3c2a", font=("Microsoft YaHei UI", 10, "bold"))
        y += 28

        for metric in self._result.metrics:
            y = self._draw_bar(y, metric.label, metric.ratio, metric.value, metric.color, bar_w)

        self.canvas.configure(scrollregion=(0, 0, width, y + 12))

    def _draw_bar(self, y: int, label: str, ratio: float, value: str, color: str, bar_w: int) -> int:
        x0 = 20
        label_w = 120
        value_w = 70
        self.canvas.create_text(x0, y + 8, anchor="nw", text=label, fill="#243f31", font=("Microsoft YaHei UI", 9))
        bar_x = x0 + label_w
        self.canvas.create_rectangle(bar_x, y + 4, bar_x + bar_w, y + 22, fill="#dfe9e3", outline="")
        fill_w = max(0, min(bar_w, int(bar_w * ratio)))
        self.canvas.create_rectangle(bar_x, y + 4, bar_x + fill_w, y + 22, fill=color, outline="")
        percent_text = f"{ratio * 100:.0f}%"
        self.canvas.create_text(bar_x + bar_w + 12, y + 8, anchor="nw", text=percent_text, fill="#335644", font=("Microsoft YaHei UI", 9))
        self.canvas.create_text(bar_x + bar_w + value_w, y + 8, anchor="ne", text=value, fill="#1d3527", font=("Consolas", 9))
        return y + 28
