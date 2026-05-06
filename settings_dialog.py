from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app_settings import (
    AppSettings,
    DEFAULT_SCAN_IGNORE_PREFIXES,
    REPAIR_SUMMARY_FILTER_OPTIONS,
    SCAN_MODE_OPTIONS,
    normalize_default_scan_mode,
    normalize_repair_summary_filter,
    normalize_scan_ignore_prefixes,
    validate_settings_payload,
)
from window_layout import center_window


class AppSettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, settings: AppSettings) -> None:
        super().__init__(parent)
        self.title("应用设置")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.resizable(True, True)
        self.minsize(760, 560)
        self.result: AppSettings | None = None

        normalized = validate_settings_payload(settings.__dict__)
        self._scan_mode_value_to_label = dict(SCAN_MODE_OPTIONS)
        self._scan_mode_label_to_value = {label: value for value, label in SCAN_MODE_OPTIONS}
        self._summary_filter_value_to_label = dict(REPAIR_SUMMARY_FILTER_OPTIONS)
        self._summary_filter_label_to_value = {label: value for value, label in REPAIR_SUMMARY_FILTER_OPTIONS}

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(outer, text="应用设置", font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        notebook = ttk.Notebook(outer)
        notebook.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        scan_tab = ttk.Frame(notebook, padding=14)
        scan_tab.columnconfigure(0, weight=1)
        scan_tab.rowconfigure(3, weight=1)
        notebook.add(scan_tab, text="扫描")

        ttk.Label(scan_tab, text="扫描忽略目录前缀", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            scan_tab,
            text="命中前缀的目录及其全部子目录都不会被扫描。默认至少保留 `_repair`，避免误扫输出目录。",
            wraplength=680,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(8, 10))

        add_row = ttk.Frame(scan_tab)
        add_row.grid(row=2, column=0, sticky="ew")
        add_row.columnconfigure(0, weight=1)
        self.prefix_var = tk.StringVar()
        entry = ttk.Entry(add_row, textvariable=self.prefix_var)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _event: self._add_prefix())
        ttk.Button(add_row, text="添加前缀", command=self._add_prefix).grid(row=0, column=1, padx=(8, 0))

        list_frame = ttk.Frame(scan_tab)
        list_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.prefix_list = tk.Listbox(list_frame, activestyle="none", font=("Consolas", 11), exportselection=False)
        prefix_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.prefix_list.yview)
        self.prefix_list.configure(yscrollcommand=prefix_scroll.set)
        self.prefix_list.grid(row=0, column=0, sticky="nsew")
        prefix_scroll.grid(row=0, column=1, sticky="ns")
        for prefix in normalized.scan_ignore_prefixes:
            self.prefix_list.insert("end", prefix)

        prefix_actions = ttk.Frame(scan_tab)
        prefix_actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(prefix_actions, text="删除选中", command=self._remove_selected).pack(side="left")
        ttk.Button(prefix_actions, text="恢复默认", command=self._restore_defaults).pack(side="left", padx=(8, 0))

        behavior_tab = ttk.Frame(notebook, padding=14)
        behavior_tab.columnconfigure(1, weight=1)
        notebook.add(behavior_tab, text="行为偏好")

        ttk.Label(behavior_tab, text="默认扫描行为", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            behavior_tab,
            text="当目录包含子目录时，可以选择每次询问，或直接使用固定扫描模式。",
            wraplength=680,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 10))

        ttk.Label(behavior_tab, text="默认扫描模式：").grid(row=2, column=0, sticky="w")
        self.scan_mode_var = tk.StringVar(value=self._scan_mode_value_to_label[normalized.default_scan_mode])
        ttk.Combobox(
            behavior_tab,
            textvariable=self.scan_mode_var,
            state="readonly",
            values=[label for _value, label in SCAN_MODE_OPTIONS],
            width=28,
        ).grid(row=2, column=1, sticky="w")

        ttk.Label(behavior_tab, text="修复完成详情默认筛选：").grid(row=3, column=0, sticky="w", pady=(16, 0))
        self.summary_filter_var = tk.StringVar(value=self._summary_filter_value_to_label[normalized.repair_summary_default_filter])
        ttk.Combobox(
            behavior_tab,
            textvariable=self.summary_filter_var,
            state="readonly",
            values=[label for _value, label in REPAIR_SUMMARY_FILTER_OPTIONS],
            width=28,
        ).grid(row=3, column=1, sticky="w", pady=(16, 0))

        ttk.Label(
            behavior_tab,
            text="后续新增设置应继续复用 app_settings.py 的统一默认值、校验、读写和容错接口。",
            wraplength=680,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(18, 0))

        buttons = ttk.Frame(outer)
        buttons.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(buttons, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="保存设置", command=self._confirm).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        center_window(self, 820, 620)

    def _current_prefixes(self) -> list[str]:
        values = [self.prefix_list.get(index) for index in range(self.prefix_list.size())]
        return normalize_scan_ignore_prefixes(values)

    def _refresh_prefix_list(self, prefixes: list[str], *, select_value: str | None = None) -> None:
        self.prefix_list.delete(0, "end")
        for prefix in normalize_scan_ignore_prefixes(prefixes):
            self.prefix_list.insert("end", prefix)
        if select_value is not None:
            for index in range(self.prefix_list.size()):
                if self.prefix_list.get(index).casefold() == select_value.casefold():
                    self.prefix_list.selection_clear(0, "end")
                    self.prefix_list.selection_set(index)
                    self.prefix_list.see(index)
                    break

    def _add_prefix(self) -> None:
        raw_value = self.prefix_var.get().strip()
        if not raw_value:
            return
        prefixes = self._current_prefixes()
        merged = normalize_scan_ignore_prefixes(prefixes + [raw_value])
        self._refresh_prefix_list(merged, select_value=raw_value)
        self.prefix_var.set("")

    def _remove_selected(self) -> None:
        selection = self.prefix_list.curselection()
        if not selection:
            return
        remove_indexes = set(selection)
        prefixes = [self.prefix_list.get(index) for index in range(self.prefix_list.size()) if index not in remove_indexes]
        self._refresh_prefix_list(prefixes)

    def _restore_defaults(self) -> None:
        self._refresh_prefix_list(list(DEFAULT_SCAN_IGNORE_PREFIXES), select_value=DEFAULT_SCAN_IGNORE_PREFIXES[0])

    def _confirm(self) -> None:
        prefixes = self._current_prefixes()
        if not prefixes:
            messagebox.showwarning("提示", "至少需要保留一个目录忽略前缀。", parent=self)
            return

        scan_mode = normalize_default_scan_mode(self._scan_mode_label_to_value.get(self.scan_mode_var.get()))
        summary_filter = normalize_repair_summary_filter(self._summary_filter_label_to_value.get(self.summary_filter_var.get()))
        self.result = AppSettings(
            scan_ignore_prefixes=prefixes,
            default_scan_mode=scan_mode,
            repair_summary_default_filter=summary_filter,
        )
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def show_app_settings_dialog(parent: tk.Widget, settings: AppSettings) -> AppSettings | None:
    dialog = AppSettingsDialog(parent, settings)
    dialog.wait_window()
    return dialog.result
