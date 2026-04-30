from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from models import AnalysisResult


class DiagnosticsChart(ttk.Frame):
    def __init__(self, master) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg="#f8fbf8", highlightthickness=0, height=420)
        self.v_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
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
        width = max(420, self.canvas.winfo_width() or 420)
        height = max(280, self.canvas.winfo_height() or 280)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        title_font, body_font, value_font, label_w, value_pad, bar_h, row_gap = self._layout_metrics(width)

        if self._result is None:
            self.canvas.create_text(
                18,
                18,
                anchor="nw",
                text="完成分析后，这里会显示不同指标的彩色条图和风险概览。",
                fill="#476051",
                font=("Microsoft YaHei UI", body_font),
            )
            return

        x0 = 20
        y = 16
        bar_x = x0 + label_w
        bar_w = max(150, width - (bar_x + value_pad))

        self.canvas.create_text(x0, y, anchor="nw", text="问题强度", fill="#1c3c2a", font=("Microsoft YaHei UI", title_font, "bold"))
        y += row_gap + 2

        issue_rows = self._result.issues[:6]
        if not issue_rows:
            self.canvas.create_text(x0, y, anchor="nw", text="当前未检测到明显问题。", fill="#4c6a57", font=("Microsoft YaHei UI", body_font))
            y += row_gap
        else:
            for issue in issue_rows:
                y = self._draw_bar(
                    y,
                    issue.label,
                    issue.score,
                    f"{issue.score:.2f}",
                    "#d35b42",
                    bar_x,
                    bar_w,
                    body_font,
                    value_font,
                    bar_h,
                    row_gap,
                )

        y += max(8, row_gap // 2)
        self.canvas.create_text(x0, y, anchor="nw", text="关键指标", fill="#1c3c2a", font=("Microsoft YaHei UI", title_font, "bold"))
        y += row_gap + 2

        for metric in self._result.metrics:
            y = self._draw_bar(
                y,
                metric.label,
                metric.ratio,
                metric.value,
                metric.color,
                bar_x,
                bar_w,
                body_font,
                value_font,
                bar_h,
                row_gap,
            )

        self.canvas.configure(scrollregion=(0, 0, width, y + 12))

    def _layout_metrics(self, width: int) -> tuple[int, int, int, int, int, int, int]:
        if width < 520:
            return 10, 8, 8, 92, 76, 16, 22
        if width < 680:
            return 10, 9, 9, 106, 84, 17, 24
        return 11, 10, 10, 120, 92, 18, 26

    def _draw_bar(
        self,
        y: int,
        label: str,
        ratio: float,
        value: str,
        color: str,
        bar_x: int,
        bar_w: int,
        body_font: int,
        value_font: int,
        bar_h: int,
        row_gap: int,
    ) -> int:
        x0 = 20
        self.canvas.create_text(x0, y + 6, anchor="nw", text=label, fill="#243f31", font=("Microsoft YaHei UI", body_font))
        self.canvas.create_rectangle(bar_x, y + 3, bar_x + bar_w, y + 3 + bar_h, fill="#dfe9e3", outline="")
        fill_w = max(0, min(bar_w, int(bar_w * ratio)))
        self.canvas.create_rectangle(bar_x, y + 3, bar_x + fill_w, y + 3 + bar_h, fill=color, outline="")
        percent_text = f"{ratio * 100:.0f}%"
        self.canvas.create_text(bar_x + bar_w + 8, y + 6, anchor="nw", text=percent_text, fill="#335644", font=("Microsoft YaHei UI", body_font))
        self.canvas.create_text(bar_x + bar_w + 68, y + 6, anchor="ne", text=value, fill="#1d3527", font=("Consolas", value_font))
        return y + row_gap
