from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from models import RepairMethod, RepairSelection
from repair_planner import get_method_labels
from window_layout import center_window


class RepairDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        methods: list[RepairMethod],
        recommended_method_ids: list[str],
        allow_adaptive: bool,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result: RepairSelection | None = None

        self.mode_var = tk.StringVar(value="adaptive" if allow_adaptive else "manual")
        self.output_folder_var = tk.StringVar(value="_repaired")
        self.filename_suffix_var = tk.StringVar(value="_fixed")
        self.use_suffix_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.method_vars = {method.method_id: tk.BooleanVar(value=method.method_id in recommended_method_ids) for method in methods}
        self.recommended_method_ids = recommended_method_ids

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="修复策略", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        ttk.Label(
            container,
            text="自动模式会按每张图片的检测结果套用推荐方法；手动模式会统一使用你勾选的方法。",
            wraplength=520,
        ).pack(anchor="w", pady=(4, 10))

        if allow_adaptive:
            ttk.Radiobutton(container, text="按检测结果自动推荐", value="adaptive", variable=self.mode_var).pack(anchor="w")
        ttk.Radiobutton(container, text="统一使用勾选的方法", value="manual", variable=self.mode_var).pack(anchor="w", pady=(0, 10))

        recommended_labels = "、".join(get_method_labels(recommended_method_ids)) or "当前没有明确推荐项"
        ttk.Label(container, text=f"当前推荐：{recommended_labels}", wraplength=520).pack(anchor="w", pady=(0, 10))

        folder_row = ttk.Frame(container)
        folder_row.pack(fill="x", pady=(0, 8))
        ttk.Label(folder_row, text="输出目录名：").pack(side="left")
        ttk.Entry(folder_row, textvariable=self.output_folder_var, width=20).pack(side="left")
        ttk.Label(folder_row, text="例如：_repaired").pack(side="left", padx=(8, 0))

        suffix_row = ttk.Frame(container)
        suffix_row.pack(fill="x", pady=(0, 10))
        ttk.Label(suffix_row, text="输出文件后缀：").pack(side="left")
        ttk.Entry(suffix_row, textvariable=self.filename_suffix_var, width=20).pack(side="left")
        ttk.Label(suffix_row, text="例如：_fixed").pack(side="left", padx=(8, 0))

        options_row = ttk.Frame(container)
        options_row.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(options_row, text="使用后缀", variable=self.use_suffix_var).pack(side="left")
        ttk.Checkbutton(options_row, text="覆盖原文件（默认关闭）", variable=self.overwrite_var).pack(side="left", padx=(12, 0))

        ttk.Label(container, text="手动修复方法", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 8))

        methods_frame = ttk.Frame(container)
        methods_frame.pack(fill="x")
        for method in methods:
            row = ttk.Frame(methods_frame)
            row.pack(fill="x", pady=2)
            ttk.Checkbutton(row, text=method.label, variable=self.method_vars[method.method_id]).pack(side="left")
            ttk.Label(row, text=method.description).pack(side="left", padx=(8, 0))

        helper_row = ttk.Frame(container)
        helper_row.pack(fill="x", pady=(10, 0))
        ttk.Button(helper_row, text="只选推荐项", command=self._set_recommended).pack(side="left")
        ttk.Button(helper_row, text="清空手动勾选", command=self._clear_methods).pack(side="left", padx=6)

        action_row = ttk.Frame(container)
        action_row.pack(fill="x", pady=(14, 0))
        ttk.Button(action_row, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(action_row, text="开始修复", command=self._confirm).pack(side="right", padx=(0, 8))
        center_window(self, 700, 620)

    def _set_recommended(self) -> None:
        for method_id, variable in self.method_vars.items():
            variable.set(method_id in self.recommended_method_ids)

    def _clear_methods(self) -> None:
        for variable in self.method_vars.values():
            variable.set(False)

    def _confirm(self) -> None:
        selected_method_ids = [method_id for method_id, variable in self.method_vars.items() if variable.get()]
        mode = self.mode_var.get()

        if mode == "manual" and not selected_method_ids:
            messagebox.showwarning("提示", "手动修复模式至少需要勾选一种修复方法。", parent=self)
            return

        output_folder_name = self.output_folder_var.get().strip() or "_repaired"
        use_suffix = self.use_suffix_var.get()
        filename_suffix = self.filename_suffix_var.get().strip() if use_suffix else ""
        if use_suffix and not filename_suffix:
            filename_suffix = "_fixed"

        self.result = RepairSelection(
            mode=mode,
            selected_method_ids=selected_method_ids,
            output_folder_name=output_folder_name,
            filename_suffix=filename_suffix,
            use_suffix=use_suffix,
            overwrite_original=self.overwrite_var.get(),
        )
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def show_repair_dialog(
    parent: tk.Widget,
    title: str,
    methods: list[RepairMethod],
    recommended_method_ids: list[str],
    allow_adaptive: bool,
) -> RepairSelection | None:
    dialog = RepairDialog(parent, title, methods, recommended_method_ids, allow_adaptive)
    dialog.wait_window()
    return dialog.result
