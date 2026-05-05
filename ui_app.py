from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps

from analyzer import analyze_image
from app_console import AppConsole
from app_metadata import APP_NAME, APP_VERSION
from cleanup_review_dialog import CleanupReviewEntry, show_cleanup_review_dialog
from debug_open_dialog import DebugOpenEntry, show_debug_open_dialog
from diagnostics_chart import DiagnosticsChart
from drag_drop import WindowsFileDropTarget
from file_actions import CleanupOperationResult, export_cleanup_list, safe_cleanup_paths, scan_image_paths, scan_image_paths_with_progress
from history_dialog import show_history_dialog
from metadata_utils import summarize_image_metadata
from models import AnalysisResult, CleanupCandidate, RepairRecord, RepairSelection
from preview_cache import ThumbnailCache
from progress_dialog import TaskProgressController
from repair_completion_dialog import show_repair_completion_dialog
from repair_dialog import show_repair_dialog
from repair_engine import repair_image_file
from repair_planner import get_method_labels, get_repair_methods, suggest_methods_for_result, suggest_methods_for_results
from result_sorting import sort_paths
from stats_dialog import show_stats_dialog
from stats_store import load_stats, record_analysis, record_repair, save_stats


FILTER_OPTIONS = [
    "全部",
    "仅问题图",
    "过曝",
    "失焦/模糊",
    "欠曝",
    "低对比度",
    "偏色",
    "噪点偏高",
    "层次不足",
    "色彩寡淡",
    "饱和度偏高",
]

ANALYSIS_PROGRESS_STEPS = 5
DEFAULT_ANALYSIS_WORKERS = max(1, min(8, os.cpu_count() or 4))
DEFAULT_REPAIR_WORKERS = max(1, min(4, max(1, (os.cpu_count() or 4) // 2)))


class PhotoAnalyzerApp:
    def __init__(self, root: tk.Misc, single_mode: bool = False) -> None:
        self.root = root
        self.single_mode = single_mode
        if self.single_mode:
            self.root.geometry("1880x1120")
            self.root.minsize(1500, 940)
        else:
            self.root.geometry("1700x1020")
            self.root.minsize(1380, 880)

        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择图片目录开始分析。" if not self.single_mode else "请选择单张图片开始分析。")
        self.filter_var = tk.StringVar(value="全部")
        self.only_problem_var = tk.BooleanVar(value=True)
        self.debug_open_after_repair_var = tk.BooleanVar(value=False)
        self.progress_text_var = tk.StringVar(value="等待任务")
        self.progress_detail_var = tk.StringVar(value="尚未开始。")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.hud_name_var = tk.StringVar(value="未选择图片")
        self.hud_risk_var = tk.StringVar(value="风险值 --")
        self.hud_tags_var = tk.StringVar(value="识别结果：等待分析")
        self.hud_methods_var = tk.StringVar(value="推荐修复：等待分析")

        self.image_paths: list[Path] = []
        self.results: dict[Path, AnalysisResult] = {}
        self.errors: dict[Path, str] = {}
        self.selected_flags: dict[Path, tk.BooleanVar] = {}
        self.cleanup_flags: dict[Path, tk.BooleanVar] = {}
        self.item_lookup: dict[str, Path] = {}
        self.cleanup_item_lookup: dict[str, Path] = {}
        self.worker_lock = threading.Lock()
        self.is_busy = False
        self.control_widgets: list[ttk.Widget] = []
        self.thumb_cache = ThumbnailCache()
        self.list_menu: tk.Menu | None = None
        self.stats = load_stats()
        self.console = AppConsole()
        self.drop_target: WindowsFileDropTarget | None = None
        self.sort_column = "name"
        self.sort_reverse = False
        self.analysis_phase_progress: dict[Path, int] = {}
        self._last_scan_update = 0.0
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._last_analysis_targets: list[Path] = []

        self._configure_style()
        self._build_ui()
        self.progress_controller = TaskProgressController(
            self.root,
            self.progress_bar,
            self.progress_value,
            self.progress_text_var,
            self.progress_detail_var,
            self.status_var,
        )
        self.root.after(25, self._drain_ui_queue)
        self._install_drag_drop()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after_idle(self._apply_initial_layout)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.configure(bg="#eef3ef")
        style.configure("TFrame", background="#eef3ef")
        style.configure("Panel.TFrame", background="#fbfcfa")
        style.configure("TopCard.TFrame", background="#f5faf6")
        style.configure("TLabel", background="#eef3ef", foreground="#1f3527", font=("Microsoft YaHei UI", 11))
        style.configure("Header.TLabel", background="#eef3ef", foreground="#17361f", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Sub.TLabel", background="#eef3ef", foreground="#45604d", font=("Microsoft YaHei UI", 11))
        style.configure("PanelTitle.TLabel", background="#fbfcfa", foreground="#1f3527", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("HudTitle.TLabel", background="#f5faf6", foreground="#163624", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("HudValue.TLabel", background="#f5faf6", foreground="#2d5640", font=("Microsoft YaHei UI", 9))
        style.configure("Treeview", font=("Microsoft YaHei UI", 10), rowheight=90)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(10, 7))
        style.configure("Soft.TButton", font=("Microsoft YaHei UI", 11), padding=(10, 7))
        style.configure("TLabelframe", background="#fbfcfa", bordercolor="#d7e3da")
        style.configure("TLabelframe.Label", background="#fbfcfa", foreground="#244333", font=("Microsoft YaHei UI", 11, "bold"))

    def _build_ui(self) -> None:
        menu_bar = tk.Menu(self.root)
        review_menu = tk.Menu(menu_bar, tearoff=False)
        review_menu.add_command(label="打开不适合保留候选", command=self.open_cleanup_review_window)
        menu_bar.add_cascade(label="查看", menu=review_menu)
        self.root.configure(menu=menu_bar)

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        top_shell = ttk.Frame(outer, style="TopCard.TFrame", padding=14)
        top_shell.pack(fill="x")
        body_shell = ttk.Frame(outer, style="Panel.TFrame", padding=(0, 12, 0, 0))
        body_shell.pack(fill="both", expand=True)

        header = ttk.Frame(top_shell, style="TopCard.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text=f"{APP_NAME} v{APP_VERSION}", style="Header.TLabel").pack(anchor="w")
        subtitle = "逐张实时分析、缩略图预览、条图诊断、自动修复与批量清理。"
        if self.single_mode:
            subtitle = "单图大窗口模式，提供独立 HUD、预览、指标条图和详细说明。"
        ttk.Label(header, text=subtitle, style="Sub.TLabel").pack(anchor="w", pady=(4, 12))

        controls = ttk.Frame(top_shell, style="Panel.TFrame", padding=14)
        controls.pack(fill="x")
        controls.columnconfigure(0, weight=1)

        path_entry = ttk.Entry(controls, textvariable=self.folder_var, font=("Consolas", 11))
        path_entry.grid(row=0, column=0, rowspan=2, sticky="ew", padx=(0, 12), pady=(0, 4))

        choose_folder_button = ttk.Button(controls, text="选择目录", command=self.choose_folder)
        choose_image_button = ttk.Button(controls, text="选择图片", command=self.choose_image)
        scan_button = ttk.Button(
            controls,
            text="读取目录" if not self.single_mode else "重新载入当前图片",
            style="Soft.TButton",
            command=self.scan_folder if not self.single_mode else self.analyze_selected,
        )
        analyze_all_button = ttk.Button(controls, text="分析全部", style="Accent.TButton", command=self.analyze_all)
        analyze_selected_button = ttk.Button(controls, text="分析选中", command=self.analyze_selected)
        single_mode_button = ttk.Button(controls, text="单图模式", command=self.open_single_mode)
        repair_current_button = ttk.Button(controls, text="修复当前", command=self.repair_current)
        denoise_current_button = ttk.Button(controls, text="去噪当前", command=self.denoise_current)
        repair_checked_button = ttk.Button(controls, text="批量修复勾选", command=self.repair_checked)
        stats_button = ttk.Button(controls, text="累计统计", command=self.show_stats)
        history_button = ttk.Button(controls, text="更新历史", command=lambda: show_history_dialog(self.root))
        export_button = ttk.Button(controls, text="导出清理清单", command=self.export_selected)
        cleanup_button = ttk.Button(controls, text="清理勾选项", command=self.cleanup_selected)

        button_specs: list[ttk.Button] = []
        if not self.single_mode:
            button_specs.append(choose_folder_button)
        button_specs.extend(
            [
                choose_image_button,
                scan_button,
                analyze_all_button,
                analyze_selected_button,
                single_mode_button,
                repair_current_button,
                denoise_current_button,
                repair_checked_button,
                stats_button,
                history_button,
                export_button,
                cleanup_button,
            ]
        )
        button_columns = 6
        for offset in range(button_columns):
            controls.columnconfigure(offset + 1, weight=1)
        for index, button in enumerate(button_specs):
            row = index // button_columns
            column = 1 + (index % button_columns)
            button.grid(row=row, column=column, sticky="ew", padx=4, pady=4)

        self.control_widgets.extend(button_specs)

        toolbar = ttk.Frame(top_shell, padding=(0, 10), style="TopCard.TFrame")
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="筛选：").pack(side="left")
        filter_box = ttk.Combobox(toolbar, textvariable=self.filter_var, state="readonly", values=FILTER_OPTIONS, width=14)
        filter_box.pack(side="left", padx=(0, 12))
        filter_box.bind("<<ComboboxSelected>>", lambda _: self.refresh_tree())
        auto_check = ttk.Checkbutton(toolbar, text="默认勾选问题图", variable=self.only_problem_var)
        auto_check.pack(side="left")
        debug_open_check = ttk.Checkbutton(
            toolbar,
            text="调试模式：修复后选择打开前后对比",
            variable=self.debug_open_after_repair_var,
        )
        debug_open_check.pack(side="left", padx=(12, 0))
        ttk.Label(toolbar, text="提示：支持目录/图片拖入，分栏边界可拖动调整。", style="Sub.TLabel").pack(side="right")
        self.control_widgets.extend([filter_box, auto_check, debug_open_check])

        progress_panel = ttk.LabelFrame(top_shell, text="任务进度", padding=14)
        progress_panel.pack(fill="x", pady=(0, 2))
        self.progress_bar = ttk.Progressbar(progress_panel, mode="determinate", maximum=1, variable=self.progress_value)
        self.progress_bar.pack(fill="x", pady=(2, 6))
        ttk.Label(progress_panel, textvariable=self.progress_text_var, style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(progress_panel, textvariable=self.progress_detail_var).pack(anchor="w", pady=(4, 0))

        main = ttk.PanedWindow(body_shell, orient="horizontal")
        main.pack(fill="both", expand=True)
        self.main_pane = main

        left = ttk.Frame(main, style="Panel.TFrame", padding=12)
        right = ttk.Frame(main, style="Panel.TFrame", padding=12)
        main.add(left, weight=2)
        main.add(right, weight=3)

        ttk.Label(left, text="缩略图结果列表", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 8))
        tree_frame = ttk.Frame(left, style="Panel.TFrame")
        tree_frame.pack(fill="both", expand=True)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("pick", "status", "risk", "tags"),
            show=("tree", "headings"),
            selectmode="extended",
        )
        self.tree.heading("#0", text="预览 / 文件名", command=lambda: self._toggle_sort("name"))
        self.tree.column("#0", width=370, anchor="w")
        self.tree.heading("pick", text="处理状态")
        self.tree.column("pick", width=92, anchor="center")
        self.tree.heading("status", text="状态", command=lambda: self._toggle_sort("status"))
        self.tree.heading("risk", text="风险值", command=lambda: self._toggle_sort("risk"))
        self.tree.heading("tags", text="识别结果", command=lambda: self._toggle_sort("tags"))
        self.tree.column("status", width=90, anchor="center")
        self.tree.column("risk", width=90, anchor="center")
        self.tree.column("tags", width=340, anchor="w")

        scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.toggle_cleanup_flag)
        self.tree.bind("<Button-1>", self.on_tree_click, add="+")
        self.tree.bind("<Button-3>", self.open_context_menu)

        self.list_menu = tk.Menu(self.root, tearoff=False)
        self.list_menu.add_command(label="切换处理状态", command=self.toggle_cleanup_flag)
        self.list_menu.add_separator()
        self.list_menu.add_command(label="移出此列表", command=self.remove_current_from_list)

        action_bar = ttk.Frame(left)
        action_bar.pack(fill="x", pady=(10, 0))
        ttk.Button(action_bar, text="选中当前", command=self.select_current).pack(side="left")
        ttk.Button(action_bar, text="取消当前", command=self.unselect_current).pack(side="left", padx=6)
        ttk.Button(action_bar, text="全选问题图", command=self.select_problem_items).pack(side="left")
        ttk.Button(action_bar, text="取消全部勾选", command=self.unselect_all).pack(side="left", padx=6)
        ttk.Button(action_bar, text="刷新列表", command=self.refresh_tree).pack(side="left")
        ttk.Label(action_bar, text="单击处理状态可切换，右键可移出列表。").pack(side="right")

        cleanup_frame = ttk.LabelFrame(left, text="不适合保留候选", padding=10)
        cleanup_frame.pack(fill="both", expand=False, pady=(12, 0))
        cleanup_frame.columnconfigure(0, weight=1)
        cleanup_frame.rowconfigure(1, weight=1)
        ttk.Label(
            cleanup_frame,
            text="分析完成后会在这里汇总高风险清理候选。默认全部不勾选，需要用户确认后才会执行安全清理。",
            style="Sub.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        cleanup_tree_frame = ttk.Frame(cleanup_frame, style="Panel.TFrame")
        cleanup_tree_frame.grid(row=1, column=0, sticky="nsew")
        cleanup_tree_frame.columnconfigure(0, weight=1)
        cleanup_tree_frame.rowconfigure(0, weight=1)

        self.cleanup_tree = ttk.Treeview(
            cleanup_tree_frame,
            columns=("pick", "severity", "confidence", "reason"),
            show=("tree", "headings"),
            selectmode="extended",
            height=5,
        )
        self.cleanup_tree.heading("#0", text="缩略图 / 文件名")
        self.cleanup_tree.column("#0", width=260, anchor="w")
        self.cleanup_tree.heading("pick", text="待处理")
        self.cleanup_tree.column("pick", width=72, anchor="center")
        self.cleanup_tree.heading("severity", text="严重度")
        self.cleanup_tree.column("severity", width=72, anchor="center")
        self.cleanup_tree.heading("confidence", text="置信度")
        self.cleanup_tree.column("confidence", width=72, anchor="center")
        self.cleanup_tree.heading("reason", text="主要原因")
        self.cleanup_tree.column("reason", width=360, anchor="w")
        cleanup_scroll = ttk.Scrollbar(cleanup_tree_frame, orient="vertical", command=self.cleanup_tree.yview)
        self.cleanup_tree.configure(yscrollcommand=cleanup_scroll.set)
        self.cleanup_tree.grid(row=0, column=0, sticky="nsew")
        cleanup_scroll.grid(row=0, column=1, sticky="ns")
        self.cleanup_tree.bind("<<TreeviewSelect>>", self.on_cleanup_tree_select)
        self.cleanup_tree.bind("<Button-1>", self.on_cleanup_tree_click, add="+")

        cleanup_action_bar = ttk.Frame(cleanup_frame)
        cleanup_action_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.cleanup_delete_button = ttk.Button(
            cleanup_action_bar,
            text="移入安全清理",
            command=self.cleanup_selected_candidates,
            state="disabled",
        )
        self.cleanup_delete_button.pack(side="left")
        ttk.Button(cleanup_action_bar, text="勾选当前", command=self.select_cleanup_current).pack(side="left", padx=(6, 0))
        ttk.Button(cleanup_action_bar, text="切换所选", command=self.toggle_selected_cleanup_candidates).pack(side="left", padx=6)
        ttk.Button(cleanup_action_bar, text="全选", command=self.select_all_cleanup_candidates).pack(side="left")
        ttk.Button(cleanup_action_bar, text="取消全选", command=self.unselect_all_cleanup_candidates).pack(side="left", padx=6)
        self.cleanup_hint_var = tk.StringVar(value="当前没有勾选候选，可直接跳过。")
        ttk.Label(cleanup_action_bar, textvariable=self.cleanup_hint_var, style="Sub.TLabel").pack(side="right")

        ttk.Label(right, text="预览、指标、诊断与信息", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 8))
        self.right_stack_pane = ttk.PanedWindow(right, orient="vertical")
        self.right_stack_pane.pack(fill="both", expand=True)

        self.bottom_right_pane = ttk.PanedWindow(self.right_stack_pane, orient="horizontal")
        chart_frame = ttk.Frame(self.right_stack_pane, style="Panel.TFrame", padding=10)
        summary_frame = ttk.Frame(self.bottom_right_pane, style="Panel.TFrame", padding=10)
        info_frame = ttk.Frame(self.bottom_right_pane, style="Panel.TFrame", padding=10)
        self.right_stack_pane.add(chart_frame, weight=4)
        self.right_stack_pane.add(self.bottom_right_pane, weight=2)
        self.bottom_right_pane.add(summary_frame, weight=3)
        self.bottom_right_pane.add(info_frame, weight=2)

        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(1, weight=1)

        hud_frame = ttk.Frame(chart_frame, style="TopCard.TFrame", padding=(10, 8))
        hud_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hud_frame.columnconfigure(0, weight=3)
        hud_frame.columnconfigure(1, weight=1)
        ttk.Label(hud_frame, textvariable=self.hud_name_var, style="HudTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hud_frame, textvariable=self.hud_risk_var, style="HudTitle.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(hud_frame, textvariable=self.hud_tags_var, style="HudValue.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        ttk.Label(hud_frame, textvariable=self.hud_methods_var, style="HudValue.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.chart = DiagnosticsChart(chart_frame)
        self.chart.grid(row=1, column=0, sticky="nsew")

        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(0, weight=1)
        self.summary_text = tk.Text(
            summary_frame,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            bg="#f8fbf8",
            relief="flat",
            padx=10,
            pady=10,
        )
        summary_scroll = ttk.Scrollbar(summary_frame, orient="vertical", command=self.summary_text.yview)
        self.summary_text.configure(yscrollcommand=summary_scroll.set)
        self.summary_text.grid(row=0, column=0, sticky="nsew")
        summary_scroll.grid(row=0, column=1, sticky="ns")
        self.summary_text.insert("1.0", "右下区域会显示当前图片的诊断说明、建议和推荐修复方法。")
        self.summary_text.config(state="disabled")

        info_frame.columnconfigure(0, weight=1)
        info_frame.rowconfigure(0, weight=1)
        info_book = ttk.Notebook(info_frame)
        info_book.grid(row=0, column=0, sticky="nsew")

        meta_tab = ttk.Frame(info_book)
        meta_tab.columnconfigure(0, weight=1)
        meta_tab.rowconfigure(0, weight=1)
        self.meta_text = tk.Text(meta_tab, wrap="word", font=("Microsoft YaHei UI", 10), bg="#f8fbf8", relief="flat", padx=10, pady=10)
        meta_scroll = ttk.Scrollbar(meta_tab, orient="vertical", command=self.meta_text.yview)
        self.meta_text.configure(yscrollcommand=meta_scroll.set)
        self.meta_text.grid(row=0, column=0, sticky="nsew")
        meta_scroll.grid(row=0, column=1, sticky="ns")
        self.meta_text.insert("1.0", "这里会显示 EXIF、DPI、ICC、XMP 等属性信息。")
        self.meta_text.config(state="disabled")

        console_tab = ttk.Frame(info_book)
        console_tab.columnconfigure(0, weight=1)
        console_tab.rowconfigure(0, weight=1)
        self.console_text = tk.Text(console_tab, wrap="word", font=("Consolas", 9), bg="#f8fbf8", relief="flat", padx=10, pady=10)
        console_scroll = ttk.Scrollbar(console_tab, orient="vertical", command=self.console_text.yview)
        self.console_text.configure(yscrollcommand=console_scroll.set)
        self.console_text.grid(row=0, column=0, sticky="nsew")
        console_scroll.grid(row=0, column=1, sticky="ns")
        self.console_text.insert("1.0", self.console.dump())
        self.console_text.config(state="disabled")

        info_book.add(meta_tab, text="属性 / EXIF")
        info_book.add(console_tab, text="Console")

        status = ttk.Label(body_shell, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", pady=(10, 0))

    def _apply_initial_layout(self) -> None:
        try:
            self.main_pane.sashpos(0, 620)
            self.bottom_right_pane.sashpos(0, 610)
            self.right_stack_pane.sashpos(0, 560)
        except Exception:
            pass

    def _install_drag_drop(self) -> None:
        try:
            self.drop_target = WindowsFileDropTarget(self.root, self._handle_dropped_paths)
            self.root.after(100, self.drop_target.install)
            self._log_console("drag and drop ready")
        except Exception as exc:
            self._log_console(f"drag and drop init failed: {exc}")

    def _dispatch_ui(self, callback) -> None:
        self._ui_queue.put(callback)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(25, self._drain_ui_queue)

    def _on_close(self) -> None:
        try:
            if self.drop_target is not None:
                self.drop_target.uninstall()
        finally:
            self.root.destroy()

    def _log_console(self, message: str) -> None:
        self.console.log(message)
        if not hasattr(self, "console_text"):
            return

        def _update_console() -> None:
            self.console_text.config(state="normal")
            self.console_text.delete("1.0", "end")
            self.console_text.insert("1.0", self.console.dump())
            self.console_text.config(state="disabled")
            self.console_text.see("end")

        if threading.current_thread() is threading.main_thread():
            _update_console()
        else:
            self._dispatch_ui(_update_console)

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="选择图片目录")
        if chosen:
            self._log_console(f"selected folder: {chosen}")
            self.folder_var.set(chosen)
            self.scan_folder()

    def choose_image(self) -> None:
        chosen = filedialog.askopenfilename(
            title="选择单张图片",
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.jfif"),
                ("所有文件", "*.*"),
            ],
        )
        if chosen:
            self._log_console(f"selected image: {chosen}")
            self.load_single_image(Path(chosen))

    def _handle_dropped_paths(self, dropped: list[Path]) -> None:
        image_paths: list[Path] = []
        for item in dropped:
            if item.is_dir():
                image_paths.extend(scan_image_paths(item))
            elif item.is_file():
                image_paths.append(item)
        if not image_paths:
            self._log_console("drag drop ignored: no supported image")
            return
        self._merge_paths(image_paths)
        self.folder_var.set(str(dropped[0]))
        self.thumb_cache.clear()
        self.refresh_tree()
        self._select_path(image_paths[0])
        self._log_console(f"drag drop added: {len(image_paths)} image(s)")

    def load_single_image(self, path: Path) -> None:
        if self.is_busy:
            messagebox.showinfo("提示", "当前有任务正在运行，请稍后。")
            return
        if not path.exists():
            messagebox.showerror("错误", "选中的图片不存在，请重新选择。")
            return

        self.folder_var.set(str(path))
        self.thumb_cache.clear()
        if self.single_mode:
            self.image_paths = [path]
            self.results.clear()
            self.errors.clear()
            self.selected_flags.clear()
            self.cleanup_flags.clear()
        else:
            self._merge_paths([path])
        self.selected_flags.setdefault(path, tk.BooleanVar(value=False))
        self.selected_flags[path].set(True)
        self.status_var.set(f"已载入图片：{path.name}")
        self.progress_text_var.set("已载入图片")
        self.progress_detail_var.set("可直接分析当前图片，或继续向列表添加更多图片。")
        self.progress_bar.configure(maximum=max(1, len(self.image_paths)))
        self.progress_value.set(0.0)
        self.refresh_tree()
        self._select_path(path)
        self.show_preview(path)
        self._log_console(f"loaded image: {path}")
        if self.single_mode:
            self._run_analysis([path])

    def scan_folder(self) -> None:
        if self.is_busy:
            messagebox.showinfo("提示", "当前有任务正在运行，请稍后。")
            return

        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("提示", "请先选择图片目录。")
            return

        root = Path(folder)
        if not root.exists():
            messagebox.showerror("错误", "目录不存在，请重新选择。")
            return

        self._last_scan_update = 0.0
        self._begin_task(
            1,
            "读取目录 0/0",
            f"正在扫描目录：{root}",
            show_dialog=True,
            dialog_title="读取目录中",
            dialog_header="正在扫描目录文件",
        )
        self._log_console(f"scan started: {root}")

        def progress_callback(done: int, total: int, found: int, current: Path | None) -> None:
            current_label = "准备扫描..."
            if current is not None:
                try:
                    current_label = str(current.relative_to(root))
                except ValueError:
                    current_label = current.name
            self._dispatch_ui(lambda: self._update_scan_progress(done, total, found, current_label))

        def worker() -> None:
            try:
                paths = scan_image_paths_with_progress(root, progress_callback)
            except Exception as exc:
                self._dispatch_ui(lambda: self._scan_failed(str(exc)))
                return
            self._dispatch_ui(lambda: self._scan_finished(paths))

        threading.Thread(target=worker, daemon=True).start()

    def analyze_all(self) -> None:
        if not self.image_paths:
            if self.single_mode:
                self.choose_image()
            else:
                self.scan_folder()
        if self.image_paths:
            self._run_analysis(self.image_paths)

    def analyze_selected(self) -> None:
        targets = [path for path in self._selected_tree_paths() if path in self.image_paths]
        if not targets:
            targets = [path for path, flag in self.selected_flags.items() if flag.get() and path in self.image_paths]
        if not targets:
            path = self._current_path()
            if path is not None:
                targets = [path]
        if not targets:
            messagebox.showinfo("提示", "请先选择至少一张图片。")
            return
        self._run_analysis(targets)

    def repair_current(self) -> None:
        path = self._current_path()
        if path is None:
            messagebox.showinfo("提示", "请先在列表中选中一张图片。")
            return
        self._open_repair_dialog([path], "修复当前图片")

    def denoise_current(self) -> None:
        path = self._current_path()
        if path is None:
            messagebox.showinfo("提示", "请先在列表中选中一张图片。")
            return
        selection = RepairSelection(
            mode="manual",
            selected_method_ids=["reduce_noise"],
            output_folder_name="_repaired",
            filename_suffix="_denoised",
        )
        self._run_repair([path], selection)

    def repair_checked(self) -> None:
        targets = [path for path in self._selected_tree_paths() if path.exists()]
        if not targets:
            targets = [path for path, flag in self.selected_flags.items() if flag.get() and path.exists()]
        if not targets:
            messagebox.showinfo("提示", "请先勾选至少一张图片。")
            return
        self._open_repair_dialog(targets, f"批量修复 {len(targets)} 张图片")

    def _open_repair_dialog(self, targets: list[Path], title: str) -> None:
        existing_results = [self.results[path] for path in targets if path in self.results]
        recommended = suggest_methods_for_results(existing_results)
        selection = show_repair_dialog(
            self.root,
            title,
            get_repair_methods(),
            recommended,
            allow_adaptive=True,
        )
        if selection is not None:
            self._run_repair(targets, selection)

    def _toggle_sort(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.refresh_tree()

    def open_single_mode(self) -> None:
        from single_image_window import open_single_image_window

        current = self._current_path()
        open_single_image_window(self.root, current)

    def show_stats(self) -> None:
        show_stats_dialog(self.root, self.stats)

    def _analysis_workers(self, total: int) -> int:
        return max(1, min(DEFAULT_ANALYSIS_WORKERS, total))

    def _repair_workers(self, total: int) -> int:
        return max(1, min(DEFAULT_REPAIR_WORKERS, total))

    def _selected_tree_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item_id in self.tree.selection():
            path = self.item_lookup.get(item_id)
            if path is not None:
                paths.append(path)
        return paths

    def _prune_missing_paths(self) -> None:
        missing = [path for path in self.image_paths if not path.exists()]
        if not missing:
            return
        for path in missing:
            self.results.pop(path, None)
            self.errors.pop(path, None)
            self.selected_flags.pop(path, None)
            self.cleanup_flags.pop(path, None)
            self.thumb_cache.evict(path)
        self.image_paths = [path for path in self.image_paths if path.exists()]

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self.control_widgets:
            widget.configure(state=state)

    def _begin_task(
        self,
        total: int,
        title: str,
        detail: str,
        *,
        show_dialog: bool = False,
        dialog_title: str | None = None,
        dialog_header: str | None = None,
    ) -> None:
        self.is_busy = True
        self._set_controls_enabled(False)
        self.progress_controller.begin(
            total=max(1, total),
            title=title,
            detail=detail,
            status=detail,
            show_dialog=show_dialog,
            dialog_title=dialog_title,
            dialog_header=dialog_header,
        )

    def _finish_task(self, title: str, detail: str) -> None:
        self.is_busy = False
        self._set_controls_enabled(True)
        self.progress_controller.finish(title=title, detail=detail, status=detail, close_dialog=True)

    def _resolve_base_folder(self) -> str:
        raw = self.folder_var.get().strip()
        if not raw:
            return "."
        candidate = Path(raw)
        if candidate.is_file():
            return str(candidate.parent)
        return str(candidate)

    def _update_scan_progress(self, done: int, total: int, found: int, current_label: str) -> None:
        import time
        now = time.time()
        if now - self._last_scan_update < 0.1 and done < total:
            return
        self._last_scan_update = now
        self.progress_controller.update(
            done=done,
            total=max(1, total),
            title=f"读取目录 {done}/{total}",
            detail=f"已发现 {found} 张图片，当前：{current_label}",
            status=f"读取目录 {done}/{total}，已发现 {found} 张图片",
            dialog_title="读取目录中",
            dialog_header="正在扫描目录文件",
        )

    def _scan_finished(self, paths: list[Path]) -> None:
        self._merge_paths(paths)
        self.thumb_cache.clear()
        self.progress_bar.configure(maximum=max(1, len(self.image_paths)))
        self.progress_value.set(0.0)
        self._log_console(f"scan finished: new={len(paths)} total={len(self.image_paths)}")
        self._finish_task("目录读取完成", f"当前列表共 {len(self.image_paths)} 张图片，本次新读取 {len(paths)} 张。")
        self.refresh_tree()
        if self.image_paths:
            self._select_path(self.image_paths[0])

    def _scan_failed(self, error: str) -> None:
        self._log_console(f"scan failed: {error}")
        self._finish_task("目录读取失败", error)
        messagebox.showerror("读取失败", f"扫描目录时发生错误：\n{error}")

    def _run_analysis(self, targets: list[Path]) -> None:
        if self.is_busy:
            messagebox.showinfo("提示", "当前已有任务正在运行。")
            return

        total = len(targets)
        if total == 0:
            return
        self.analysis_phase_progress = {path: 0 for path in targets}
        self._last_analysis_targets = list(targets)
        worker_count = self._analysis_workers(total)

        self._log_console(f"analysis started: count={total} workers={worker_count}")
        self._begin_task(
            total * ANALYSIS_PROGRESS_STEPS,
            f"分析中 0/{total}",
            f"正在分析 {total} 张图片，请稍候...",
            show_dialog=True,
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
        )

        for path in targets:
            self.errors.pop(path, None)

        def worker() -> None:
            done = 0
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = {}
                for path in targets:
                    futures[
                        pool.submit(
                            analyze_image,
                            path,
                            lambda step, steps, phase, p=path: self._dispatch_ui(
                                lambda p=p, step=step, steps=steps, phase=phase: self._update_analysis_phase(
                                    p, step, steps, phase, total
                                )
                            ),
                        )
                    ] = path

                for future in as_completed(futures):
                    path = futures[future]
                    result: AnalysisResult | None = None
                    error: str | None = None
                    try:
                        result = future.result()
                    except Exception as exc:
                        error = str(exc)
                    done += 1
                    self._dispatch_ui(
                        lambda p=path, r=result, e=error, d=done, t=total: self._handle_analysis_item_done(
                            p, r, e, d, t
                        )
                    )

            self._dispatch_ui(lambda: self._analysis_finished(total))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_analysis_item_done(
        self,
        path: Path,
        result: AnalysisResult | None,
        error: str | None,
        done: int,
        total: int,
    ) -> None:
        with self.worker_lock:
            if error:
                self.errors[path] = error
                self.results.pop(path, None)
                self._log_console(f"analysis failed: {path.name} | {error}")
            elif result is not None:
                self.results[path] = result
                self.errors.pop(path, None)
                labels = ",".join(issue.code for issue in result.issues) if result.issues else "ok"
                face_total = result.face_count
                face_validated = result.validated_face_count
                self._log_console(
                    f"analysis done: {path.name} | score={result.overall_score:.2f} | {labels} | "
                    f"faces={face_total}/{face_validated} | portrait={result.portrait_likely}"
                )
                for candidate in result.face_candidates:
                    if candidate.accepted or not candidate.rejection_reasons:
                        continue
                    self._log_console(
                        f"face candidate rejected: {path.name} | box={candidate.box} | "
                        f"conf={candidate.confidence:.2f} | {' / '.join(candidate.rejection_reasons)}"
                    )
                if result.portrait_rejection_reason:
                    self._log_console(f"portrait-aware skipped: {path.name} | {result.portrait_rejection_reason}")
                for cleanup_candidate in result.cleanup_candidates:
                    self._log_console(
                        f"cleanup candidate: {path.name} | {cleanup_candidate.reason_code} | "
                        f"{cleanup_candidate.severity} | conf={cleanup_candidate.confidence:.2f}"
                    )
                for note in result.perf_notes:
                    self._log_console(f"analysis perf: {path.name} | {note}")
                if self.only_problem_var.get() and result.issues:
                    self.selected_flags.setdefault(path, tk.BooleanVar(value=False))
                    self.selected_flags[path].set(True)
                if path in self.cleanup_flags and path not in self._primary_cleanup_candidates():
                    self.cleanup_flags.pop(path, None)
                self.stats = record_analysis(
                    self.stats,
                    image_bytes=path.stat().st_size if path.exists() else 0,
                    has_issue=bool(result.issues),
                )
                save_stats(self.stats)

        self.progress_controller.update(
            done=sum(self.analysis_phase_progress.values()),
            total=total * ANALYSIS_PROGRESS_STEPS,
            title=f"分析中 {done}/{total}",
            detail=f"最近完成：{path.name}",
            status=f"分析进度 {done}/{total}，最近完成：{path.name}",
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
        )
        self.refresh_tree()
        current = self._current_path()
        if current is None:
            self._select_path(path)
        elif current == path:
            self.show_preview(path)

    def _run_repair(self, targets: list[Path], selection: RepairSelection) -> None:
        if self.is_busy:
            messagebox.showinfo("提示", "当前已有任务正在运行。")
            return

        missing = [path for path in targets if path not in self.results and path not in self.errors]
        total_steps = len(missing) + len(targets)
        analysis_workers = self._analysis_workers(len(missing)) if missing else 0
        repair_workers = self._repair_workers(len(targets))
        self._log_console(
            f"repair started: count={len(targets)} pre_analyze={len(missing)} mode={selection.mode} overwrite={selection.overwrite_original} "
            f"analysis_workers={analysis_workers or 0} repair_workers={repair_workers}"
        )
        self._begin_task(
            total_steps,
            f"修复准备 0/{total_steps}",
            "正在准备修复任务...",
            show_dialog=True,
            dialog_title="修复图片中",
            dialog_header="正在分析并修复图片",
        )

        def worker() -> None:
            step = 0
            repaired: list[RepairRecord] = []
            skipped: list[RepairRecord] = []
            failed: list[tuple[Path, str]] = []
            failed_paths: set[Path] = set()

            if missing:
                with ThreadPoolExecutor(max_workers=analysis_workers) as pool:
                    futures = {pool.submit(analyze_image, path): path for path in missing}
                    for future in as_completed(futures):
                        path = futures[future]
                        try:
                            result = future.result()
                        except Exception as exc:
                            with self.worker_lock:
                                self.errors[path] = str(exc)
                            failed.append((path, str(exc)))
                            failed_paths.add(path)
                            self._log_console(f"repair pre-analysis failed: {path.name} | {exc}")
                        else:
                            with self.worker_lock:
                                self.results[path] = result
                                self.errors.pop(path, None)
                        step += 1
                        self._dispatch_ui(lambda s=step, t=total_steps, name=path.name: self._update_progress(s, t, name, "修复前分析"))

            repair_targets = [path for path in targets if path not in failed_paths]
            with ThreadPoolExecutor(max_workers=repair_workers) as pool:
                futures = {}
                for path in repair_targets:
                    if path in self.errors:
                        if path not in failed_paths:
                            failed.append((path, self.errors[path]))
                            failed_paths.add(path)
                        step += 1
                        self._dispatch_ui(lambda s=step, t=total_steps, name=path.name: self._update_progress(s, t, name, "跳过失败项"))
                        continue
                    futures[pool.submit(repair_image_file, path, self.results.get(path), selection, self._resolve_base_folder())] = path

                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        record = future.result()
                    except Exception as exc:
                        failed.append((path, str(exc)))
                        failed_paths.add(path)
                        self._log_console(f"repair failed: {path.name} | {exc}")
                    else:
                        if record is None:
                            skipped.append(
                                RepairRecord(
                                    source_path=path,
                                    output_path=path,
                                    method_ids=[],
                                    op_strengths={},
                                    saved_output=False,
                                    skipped_reason="修复引擎未返回可保存结果。",
                                )
                            )
                            self._log_console(f"repair skipped: {path.name} | 修复引擎未返回可保存结果。")
                        else:
                            if not record.saved_output:
                                skipped.append(record)
                                reason = record.skipped_reason or "当前方案未生成修复输出。"
                                self._log_console(f"repair skipped: {path.name} | {reason}")
                                for note in record.policy_notes:
                                    self._log_console(f"repair note: {path.name} | {note}")
                                for note in record.perf_notes:
                                    self._log_console(f"repair perf: {path.name} | {note}")
                            else:
                                repaired.append(record)
                                self._log_console(f"repair done: {path.name} -> {record.output_path}")
                                for note in record.policy_notes:
                                    self._log_console(f"repair note: {path.name} | {note}")
                                for note in record.perf_notes:
                                    self._log_console(f"repair perf: {path.name} | {note}")
                                self.stats = record_repair(
                                    self.stats,
                                    image_bytes=record.output_path.stat().st_size if record.output_path.exists() else 0,
                                )
                                save_stats(self.stats)

                    step += 1
                    self._dispatch_ui(lambda s=step, t=total_steps, name=path.name: self._update_progress(s, t, name, "修复中"))

            for path in targets:
                if path in self.errors:
                    if path not in failed_paths:
                        failed.append((path, self.errors[path]))
                        failed_paths.add(path)
                    if path not in repair_targets:
                        step += 1
                        self._dispatch_ui(lambda s=step, t=total_steps, name=path.name: self._update_progress(s, t, name, "跳过失败项"))

            self._dispatch_ui(lambda: self._repair_finished(repaired, skipped, failed, selection))

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, done: int, total: int, filename: str, phase: str) -> None:
        self.progress_controller.update(
            done=done,
            total=total,
            title=f"{phase} {done}/{total}",
            detail=f"最近处理：{filename}",
            status=f"{phase} {done}/{total}，最近处理：{filename}",
            dialog_title="修复图片中",
            dialog_header="正在分析并修复图片",
        )

    def _update_analysis_phase(self, path: Path, step: int, steps: int, phase: str, total_images: int) -> None:
        normalized_step = max(0, min(ANALYSIS_PROGRESS_STEPS, int(round(step * ANALYSIS_PROGRESS_STEPS / max(1, steps)))))
        previous = self.analysis_phase_progress.get(path, 0)
        if normalized_step > previous:
            self.analysis_phase_progress[path] = normalized_step
        aggregate_done = sum(self.analysis_phase_progress.values())
        finished_images = sum(1 for value in self.analysis_phase_progress.values() if value >= ANALYSIS_PROGRESS_STEPS)
        detail = f"正在分析：{path.name} | {phase} {step}/{steps}"
        if total_images > 1:
            detail = f"批量分析 {finished_images}/{total_images} | {path.name} | {phase} {step}/{steps}"
        self.progress_controller.update(
            done=aggregate_done,
            total=max(1, total_images * ANALYSIS_PROGRESS_STEPS),
            detail=detail,
            status=detail,
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
        )

    def _analysis_finished(self, total: int) -> None:
        issue_count = sum(1 for result in self.results.values() if result.issues)
        error_count = len(self.errors)
        detail = f"分析完成：问题图片 {issue_count} 张，失败 {error_count} 张。"
        self._log_console(f"analysis finished: count={total} issues={issue_count} errors={error_count}")
        self.analysis_phase_progress = {}
        self.progress_controller.update(
            done=total * ANALYSIS_PROGRESS_STEPS,
            total=max(1, total * ANALYSIS_PROGRESS_STEPS),
            title=f"分析完成 {total}/{total}",
            detail=detail,
            status=detail,
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
        )
        self._finish_task(f"分析完成 {total}/{total}", detail)
        current = self._current_path()
        if current is not None:
            self.show_preview(current)
        self._maybe_prompt_cleanup_candidates(self._last_analysis_targets)
        self._last_analysis_targets = []

    def _maybe_prompt_cleanup_candidates(self, paths: list[Path]) -> None:
        if not paths:
            return
        primary_candidates = self._primary_cleanup_candidates()
        matched_paths = [path for path in paths if path in primary_candidates]
        if not matched_paths:
            return

        first_path = matched_paths[0]
        self._select_path(first_path)
        self._select_cleanup_path(first_path)
        entries = [
            CleanupReviewEntry(
                image_path=path,
                display_name=path.name,
                reason_code=primary_candidates[path].reason_code,
                reason_text=primary_candidates[path].reason_text,
                severity=primary_candidates[path].severity,
                confidence=primary_candidates[path].confidence,
            )
            for path in matched_paths
        ]
        dialog_result = show_cleanup_review_dialog(self.root, entries)
        if dialog_result is None:
            return

        for path in matched_paths:
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
            self.cleanup_flags[path].set(False)
        for path in dialog_result.chosen_paths:
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
            self.cleanup_flags[path].set(True)
        self.refresh_tree()
        if dialog_result.chosen_paths:
            self._select_path(dialog_result.chosen_paths[0])
            self._select_cleanup_path(dialog_result.chosen_paths[0])
        if dialog_result.action == "delete" and dialog_result.chosen_paths:
            self.cleanup_selected_candidates()

    def open_cleanup_review_window(self) -> None:
        self._prune_missing_paths()
        primary_candidates = self._primary_cleanup_candidates()
        if not primary_candidates:
            messagebox.showinfo("提示", "当前没有可重新查看的不适合保留候选。")
            return
        ordered_paths = [path for path in self._sorted_paths() if path in primary_candidates]
        entries = [
            CleanupReviewEntry(
                image_path=path,
                display_name=path.name,
                reason_code=primary_candidates[path].reason_code,
                reason_text=primary_candidates[path].reason_text,
                severity=primary_candidates[path].severity,
                confidence=primary_candidates[path].confidence,
            )
            for path in ordered_paths
        ]
        dialog_result = show_cleanup_review_dialog(self.root, entries)
        if dialog_result is None:
            return
        for path in primary_candidates:
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
            self.cleanup_flags[path].set(False)
        for path in dialog_result.chosen_paths:
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
            self.cleanup_flags[path].set(True)
        self.refresh_tree()
        if dialog_result.action == "delete" and dialog_result.chosen_paths:
            self.cleanup_selected_candidates()

    def _repair_finished(
        self,
        repaired: list[RepairRecord],
        skipped: list[RepairRecord],
        failed: list[tuple[Path, str]],
        selection: RepairSelection,
    ) -> None:
        total = len(repaired) + len(skipped) + len(failed)
        detail = f"修复完成：成功 {len(repaired)} 张，跳过 {len(skipped)} 张，失败 {len(failed)} 张。"
        self._log_console(
            f"repair finished: success={len(repaired)} skipped={len(skipped)} failed={len(failed)} overwrite={selection.overwrite_original}"
        )
        self.progress_controller.update(
            done=total,
            total=max(1, total),
            title=f"修复完成 {total}/{total}",
            detail=detail,
            status=detail,
            dialog_title="修复图片中",
            dialog_header="正在分析并修复图片",
        )
        self._finish_task(f"修复完成 {total}/{total}", detail)

        for record in repaired:
            if record.source_path in self.selected_flags:
                self.selected_flags[record.source_path].set(False)

        self.refresh_tree()

        lines = [
            f"已修复 {len(repaired)} 张",
            f"已跳过 {len(skipped)} 张",
            f"失败 {len(failed)} 张",
        ]
        if selection.mode == "manual":
            labels = "、".join(get_method_labels(selection.selected_method_ids)) or "无"
            lines.append(f"统一方法：{labels}")
        else:
            lines.append("修复模式：按检测结果自动推荐")

        if selection.overwrite_original:
            lines.append("输出方式：覆盖原文件")
        else:
            lines.append(f"输出目录：{Path(self._resolve_base_folder()).resolve() / selection.output_folder_name}")
            lines.append(f"文件后缀：{selection.filename_suffix or '(无后缀)'}")
        detail_lines: list[str] = []
        if repaired:
            detail_lines.append("成功记录：")
            for record in repaired:
                detail_lines.append(
                    f"- {record.source_path.name} -> {record.output_path.name} | "
                    f"ops={','.join(record.method_ids) or 'none'} | "
                    f"strengths={', '.join(f'{k}:{v:.2f}' for k, v in record.op_strengths.items()) or 'none'}"
                )
                for note in record.policy_notes:
                    detail_lines.append(f"  note: {note}")
                for warning in record.warnings:
                    detail_lines.append(f"  warning: {warning}")
        if skipped:
            if detail_lines:
                detail_lines.append("")
            detail_lines.append("跳过记录：")
            for record in skipped:
                reason = record.skipped_reason or "当前方案未生成修复输出。"
                detail_lines.append(
                    f"- {record.source_path.name} | reason={reason} | "
                    f"ops={','.join(record.method_ids) or 'none'} | "
                    f"strengths={', '.join(f'{k}:{v:.2f}' for k, v in record.op_strengths.items()) or 'none'}"
                )
                for note in record.policy_notes:
                    detail_lines.append(f"  note: {note}")
        if failed:
            if detail_lines:
                detail_lines.append("")
            detail_lines.append("失败详情：")
            for path, message in failed:
                detail_lines.append(f"- {path.name}：{message}")
        show_repair_completion_dialog(
            self.root,
            title="修复完成",
            summary_lines=lines,
            detail_lines=detail_lines,
        )

        if self.debug_open_after_repair_var.get() and repaired:
            entries = [
                DebugOpenEntry(
                    display_name=record.source_path.name,
                    source_path=record.source_path,
                    output_path=record.output_path,
                )
                for record in repaired
            ]
            chosen = show_debug_open_dialog(self.root, entries)
            if chosen:
                self._open_debug_pairs(chosen)

    def _open_debug_pairs(self, entries: list[DebugOpenEntry]) -> None:
        missing: list[str] = []
        open_targets: list[Path] = []
        for entry in entries:
            for path, label in ((entry.source_path, "原图"), (entry.output_path, "修复图")):
                if not path.exists():
                    message = f"{entry.display_name} 的{label}不存在：{path}"
                    missing.append(message)
                    self._log_console(f"debug open missing: {message}")
                    continue
                open_targets.append(path)

        if missing:
            messagebox.showwarning("打开失败", "以下文件不存在，已跳过：\n\n" + "\n".join(missing[:8]))

        if not open_targets:
            return

        def worker() -> None:
            errors: list[str] = []
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                errors.append("当前系统不支持 os.startfile。")
            else:
                for path in open_targets:
                    try:
                        startfile(str(path))
                    except Exception as exc:
                        errors.append(f"{path.name}: {exc}")
                        self._log_console(f"debug open failed: {path} | {exc}")
            if errors:
                self._dispatch_ui(
                    lambda msgs=errors: messagebox.showwarning("打开失败", "部分文件未能打开：\n\n" + "\n".join(msgs[:8]))
                )

        threading.Thread(target=worker, daemon=True).start()

    def _sorted_paths(self) -> list[Path]:
        visible: list[Path] = []
        for path in self.image_paths:
            result = self.results.get(path)
            error = self.errors.get(path)
            if self._matches_filter(result, error):
                visible.append(path)
        return sort_paths(visible, self.results, self.errors, self.sort_column, self.sort_reverse)

    def _cleanup_severity_rank(self, severity: str) -> int:
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        return order.get(severity.lower(), 0)

    def _primary_cleanup_candidates(self) -> dict[Path, CleanupCandidate]:
        primary: dict[Path, CleanupCandidate] = {}
        for path, result in self.results.items():
            if not result.cleanup_candidates:
                continue
            best = sorted(
                result.cleanup_candidates,
                key=lambda candidate: (
                    self._cleanup_severity_rank(candidate.severity),
                    candidate.confidence,
                ),
                reverse=True,
            )[0]
            primary[path] = best
        return primary

    def _current_cleanup_path(self) -> Path | None:
        selection = self.cleanup_tree.selection()
        if not selection:
            return None
        return self.cleanup_item_lookup.get(selection[0])

    def _refresh_cleanup_tree(self) -> None:
        current_path = self._current_cleanup_path()
        primary_candidates = self._primary_cleanup_candidates()
        for item in self.cleanup_tree.get_children():
            self.cleanup_tree.delete(item)
        self.cleanup_item_lookup.clear()

        for path in list(self.cleanup_flags):
            if path not in primary_candidates:
                self.cleanup_flags.pop(path, None)
        for path in primary_candidates:
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))

        ordered_paths = sort_paths(
            [path for path in self.image_paths if path in primary_candidates],
            self.results,
            self.errors,
            self.sort_column,
            self.sort_reverse,
        )
        for path in ordered_paths:
            candidate = primary_candidates[path]
            checked = "已选" if self.cleanup_flags.get(path, tk.BooleanVar(value=False)).get() else "待定"
            confidence = f"{candidate.confidence:.2f}"
            thumb = self.thumb_cache.get_tree_thumbnail(path)
            item_id = self.cleanup_tree.insert(
                "",
                "end",
                text=path.name,
                image=thumb,
                values=(checked, candidate.severity, confidence, candidate.reason_text),
            )
            self.cleanup_item_lookup[item_id] = path
            if path == current_path:
                self.cleanup_tree.selection_set(item_id)

        self._update_cleanup_controls()

    def _update_cleanup_controls(self) -> None:
        selected_count = len([path for path, flag in self.cleanup_flags.items() if flag.get()])
        if selected_count > 0:
            self.cleanup_delete_button.configure(state="normal")
            self.cleanup_hint_var.set(f"已勾选 {selected_count} 张候选，左侧按钮会执行安全清理。")
        else:
            self.cleanup_delete_button.configure(state="disabled")
            self.cleanup_hint_var.set("当前没有勾选候选，可直接跳过。")

    def refresh_tree(self) -> None:
        self._prune_missing_paths()
        current_path = self._current_path()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.item_lookup.clear()

        for path in self._sorted_paths():
            result = self.results.get(path)
            error = self.errors.get(path)
            checked = "已选" if self.selected_flags.get(path, tk.BooleanVar(value=False)).get() else "待定"
            status = "失败" if error else "已分析" if result else "未分析"
            risk = "-" if error or not result else f"{result.overall_score:.2f}"
            if error:
                tags = "分析失败"
            elif result and result.issues:
                tags = "、".join(issue.label for issue in result.issues)
            elif result:
                tags = "正常"
            else:
                tags = ""

            thumb = self.thumb_cache.get_tree_thumbnail(path)
            item_id = self.tree.insert("", "end", text=path.name, image=thumb, values=(checked, status, risk, tags))
            self.item_lookup[item_id] = path
            if path == current_path:
                self.tree.selection_set(item_id)
        self._refresh_cleanup_tree()

    def _matches_filter(self, result: AnalysisResult | None, error: str | None) -> bool:
        chosen = self.filter_var.get()
        if chosen == "全部":
            return True
        if error:
            return False
        if chosen == "仅问题图":
            return bool(result and result.issues)
        if not result:
            return False
        return any(issue.label == chosen for issue in result.issues)

    def _current_path(self) -> Path | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.item_lookup.get(selection[0])

    def _select_path(self, path: Path) -> None:
        for item_id, item_path in self.item_lookup.items():
            if item_path == path:
                self.tree.selection_set(item_id)
                self.tree.see(item_id)
                self.show_preview(path)
                break

    def _select_cleanup_path(self, path: Path) -> None:
        for item_id, item_path in self.cleanup_item_lookup.items():
            if item_path == path:
                self.cleanup_tree.selection_set(item_id)
                self.cleanup_tree.see(item_id)
                break

    def _show_selection_summary(self, paths: list[Path]) -> None:
        selected = [path for path in paths if path in self.image_paths]
        if not selected:
            self._clear_hud_and_summary()
            return
        issue_count = 0
        analyzed_count = 0
        scene_types: dict[str, int] = {}
        exposure_types: dict[str, int] = {}
        color_types: dict[str, int] = {}
        cleanup_count = 0
        for path in selected:
            result = self.results.get(path)
            if result is None:
                continue
            analyzed_count += 1
            issue_count += int(bool(result.issues))
            scene_types[result.scene_type] = scene_types.get(result.scene_type, 0) + 1
            exposure_types[result.exposure_type] = exposure_types.get(result.exposure_type, 0) + 1
            color_types[result.color_type] = color_types.get(result.color_type, 0) + 1
            cleanup_count += int(bool(result.cleanup_candidates))

        self.chart.update_result(None)
        self.hud_name_var.set(f"已多选 {len(selected)} 张图片")
        self.hud_risk_var.set(f"已分析 {analyzed_count}/{len(selected)}")
        scene_label = "、".join(f"{name}:{count}" for name, count in list(scene_types.items())[:3]) or "待分析"
        self.hud_tags_var.set(f"识别结果：问题图 {issue_count} 张 | 清理候选 {cleanup_count} 张 | 场景 {scene_label}")
        self.hud_methods_var.set("推荐修复：多选状态下请使用“分析选中”或“批量修复勾选”")
        self._set_meta_summary("多选状态下不显示单张 EXIF 摘要。请切回单选查看详细属性。")
        lines = [
            f"当前多选 {len(selected)} 张图片。",
            f"已分析 {analyzed_count} 张，其中问题图 {issue_count} 张，清理候选 {cleanup_count} 张。",
            "",
            "scene_type 汇总：",
        ]
        for name, count in scene_types.items():
            lines.append(f"- {name}: {count}")
        lines.append("")
        lines.append("exposure_type 汇总：")
        for name, count in exposure_types.items():
            lines.append(f"- {name}: {count}")
        lines.append("")
        lines.append("color_type 汇总：")
        for name, count in color_types.items():
            lines.append(f"- {name}: {count}")
        lines.append("")
        lines.append("提示：")
        lines.append("- 可继续用 Ctrl/Shift 扩展多选。")
        lines.append("- “分析选中”会按当前选择批量分析。")
        lines.append("- “批量修复勾选”会优先处理当前多选；如无多选则回退到勾选状态。")
        self._set_summary("\n".join(lines))

    def on_tree_select(self, _event=None) -> None:
        paths = self._selected_tree_paths()
        if len(paths) > 1:
            self._show_selection_summary(paths)
            return
        path = paths[0] if paths else self._current_path()
        if path is not None:
            self.show_preview(path)

    def on_tree_click(self, event) -> None:
        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item_id:
            return
        if column == "#1":
            self.tree.selection_set(item_id)
            path = self.item_lookup.get(item_id)
            if path is None:
                return
            self.selected_flags.setdefault(path, tk.BooleanVar(value=False))
            self.selected_flags[path].set(not self.selected_flags[path].get())
            self.refresh_tree()
            self._select_path(path)

    def on_cleanup_tree_select(self, _event=None) -> None:
        path = self._current_cleanup_path()
        if path is not None:
            self._select_path(path)

    def on_cleanup_tree_click(self, event) -> None:
        item_id = self.cleanup_tree.identify_row(event.y)
        column = self.cleanup_tree.identify_column(event.x)
        if not item_id:
            return
        self.cleanup_tree.selection_set(item_id)
        path = self.cleanup_item_lookup.get(item_id)
        if path is None:
            return
        if column == "#1":
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
            self.cleanup_flags[path].set(not self.cleanup_flags[path].get())
            self._refresh_cleanup_tree()
            self._select_cleanup_path(path)
            self._select_path(path)

    def select_cleanup_current(self) -> None:
        path = self._current_cleanup_path() or self._current_path()
        if path is None or path not in self._primary_cleanup_candidates():
            return
        self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
        self.cleanup_flags[path].set(True)
        self._refresh_cleanup_tree()
        self._select_path(path)

    def toggle_selected_cleanup_candidates(self) -> None:
        selection = self.cleanup_tree.selection()
        if not selection:
            return
        paths = [self.cleanup_item_lookup[item_id] for item_id in selection if item_id in self.cleanup_item_lookup]
        if not paths:
            return
        first_path = paths[0]
        self.cleanup_flags.setdefault(first_path, tk.BooleanVar(value=False))
        target_state = not self.cleanup_flags[first_path].get()
        for path in paths:
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
            self.cleanup_flags[path].set(target_state)
        self._refresh_cleanup_tree()
        self._select_cleanup_path(first_path)
        self._select_path(first_path)

    def select_all_cleanup_candidates(self) -> None:
        for path in self._primary_cleanup_candidates():
            self.cleanup_flags.setdefault(path, tk.BooleanVar(value=False))
            self.cleanup_flags[path].set(True)
        self._refresh_cleanup_tree()

    def unselect_all_cleanup_candidates(self) -> None:
        for flag in self.cleanup_flags.values():
            flag.set(False)
        self._refresh_cleanup_tree()

    def open_context_menu(self, event) -> None:
        item_id = self.tree.identify_row(event.y)
        if not item_id or self.list_menu is None:
            return
        self.tree.selection_set(item_id)
        self.list_menu.tk_popup(event.x_root, event.y_root)

    def remove_current_from_list(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        paths = [self.item_lookup[item_id] for item_id in selection if item_id in self.item_lookup]
        if not paths:
            return
        for path in paths:
            self._remove_path_from_list(path, refresh=False)
        self.refresh_tree()
        if self.image_paths:
            self._select_path(self.image_paths[0])
        else:
            self._clear_hud_and_summary()

    def _merge_paths(self, paths: list[Path]) -> None:
        existing = set(self.image_paths)
        for path in paths:
            if path not in existing:
                self.image_paths.append(path)
                existing.add(path)
                self.selected_flags[path] = tk.BooleanVar(value=True)
            else:
                self.selected_flags.setdefault(path, tk.BooleanVar(value=False))

    def _remove_path_from_list(self, path: Path, refresh: bool = True) -> None:
        if path in self.image_paths:
            self.image_paths = [item for item in self.image_paths if item != path]
        self.results.pop(path, None)
        self.errors.pop(path, None)
        self.selected_flags.pop(path, None)
        self.cleanup_flags.pop(path, None)
        self.thumb_cache.evict(path)
        self._log_console(f"removed from list: {path}")
        if refresh:
            self.refresh_tree()
            if self.image_paths:
                self._select_path(self.image_paths[0])
            else:
                self._clear_hud_and_summary()

    def _clear_hud_and_summary(self) -> None:
        self.chart.update_result(None)
        self.hud_name_var.set("未选择图片")
        self.hud_risk_var.set("风险值 --")
        self.hud_tags_var.set("识别结果：等待分析")
        self.hud_methods_var.set("推荐修复：等待分析")
        self._set_meta_summary("当前列表为空，暂无可查看的属性信息。")
        self._set_summary("当前列表为空。可继续添加目录、拖入图片或手动选择单张图片。")

    def toggle_cleanup_flag(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        paths = [self.item_lookup[item_id] for item_id in selection if item_id in self.item_lookup]
        if not paths:
            return
        
        # Determine the target state based on the first item
        first_path = paths[0]
        self.selected_flags.setdefault(first_path, tk.BooleanVar(value=False))
        target_state = not self.selected_flags[first_path].get()

        for path in paths:
            self.selected_flags.setdefault(path, tk.BooleanVar(value=False))
            self.selected_flags[path].set(target_state)
        self.refresh_tree()
        self._select_path(first_path)

    def select_problem_items(self) -> None:
        for path, result in self.results.items():
            self.selected_flags.setdefault(path, tk.BooleanVar(value=False))
            self.selected_flags[path].set(bool(result.issues))
        self.refresh_tree()

    def select_current(self) -> None:
        path = self._current_path()
        if path is None:
            return
        self.selected_flags.setdefault(path, tk.BooleanVar(value=False))
        self.selected_flags[path].set(True)
        self.refresh_tree()
        self._select_path(path)

    def unselect_current(self) -> None:
        path = self._current_path()
        if path is None:
            return
        self.selected_flags.setdefault(path, tk.BooleanVar(value=False))
        self.selected_flags[path].set(False)
        self.refresh_tree()
        self._select_path(path)

    def unselect_all(self) -> None:
        for flag in self.selected_flags.values():
            flag.set(False)
        self.refresh_tree()

    def show_preview(self, path: Path) -> None:
        result = self.results.get(path)
        error = self.errors.get(path)

        try:
            with Image.open(path) as img:
                image = ImageOps.exif_transpose(img).convert("RGB")
        except Exception as exc:
            self.chart.update_result(None)
            self._set_summary(f"无法加载预览：{exc}")
            self._set_meta_summary(f"文件：{path.name}\n\n读取失败：{exc}")
            self._update_hud(path, None, None, str(exc))
            return
        self.chart.update_result(result)
        self._update_hud(path, image, result, error)
        self._set_meta_summary(summarize_image_metadata(path))

        lines = [
            f"文件：{path.name}",
            f"路径：{path}",
            f"尺寸：{image.width} x {image.height}",
        ]
        if error:
            lines.append("")
            lines.append(f"分析失败：{error}")
        elif result:
            lines.append(f"总体风险值：{result.overall_score:.2f}")
            lines.append("")
            lines.append(
                f"人像判断：{'是' if result.portrait_likely else '否'} | "
                f"raw/有效/拒绝：{result.raw_face_count}/{result.validated_face_count}/{result.rejected_face_count}"
            )
            lines.append(f"portrait_type：{result.portrait_type}")
            lines.append(f"scene_type：{result.scene_type}")
            lines.append(f"exposure_type：{result.exposure_type}")
            lines.append(f"color_type：{result.color_type}")
            if result.portrait_scene_type:
                lines.append(f"人像场景：{result.portrait_scene_type}")
            if result.portrait_repair_policy:
                lines.append(f"修复策略：{result.portrait_repair_policy}")
            if result.portrait_rejection_reason:
                lines.append(f"未启用 portrait-aware：{result.portrait_rejection_reason}")
            rejected_face_notes = [
                f"{candidate.box} | {candidate.confidence:.2f} | {' / '.join(candidate.rejection_reasons)}"
                for candidate in result.face_candidates
                if not candidate.accepted and candidate.rejection_reasons
            ]
            if rejected_face_notes:
                lines.append("低置信度候选拒绝：")
                for note in rejected_face_notes[:4]:
                    lines.append(f"- {note}")
            if result.cleanup_candidates:
                primary_cleanup = sorted(
                    result.cleanup_candidates,
                    key=lambda candidate: (self._cleanup_severity_rank(candidate.severity), candidate.confidence),
                    reverse=True,
                )[0]
                lines.append("")
                lines.append("不适合保留候选：")
                lines.append(
                    f"- {primary_cleanup.reason_code} | {primary_cleanup.severity} | {primary_cleanup.confidence:.2f}"
                )
                lines.append(f"  原因：{primary_cleanup.reason_text}")
            if result.perf_notes:
                lines.append("性能提示：")
                for note in result.perf_notes:
                    lines.append(f"- {note}")
                lines.append("")
            lines.append("关键指标：")
            for metric in result.metrics:
                lines.append(f"- {metric.label}：{metric.value}")
            lines.append("")
            if result.issues:
                lines.append("识别问题：")
                for issue in result.issues:
                    lines.append(f"- {issue.label} | {issue.level} | {issue.score:.2f}")
                    lines.append(f"  判断：{issue.detail}")
                    lines.append(f"  建议：{issue.suggestion}")
                recommended = suggest_methods_for_result(result)
                lines.append("")
                lines.append(f"推荐修复：{'、'.join(get_method_labels(recommended)) or '暂无明确推荐'}")
            else:
                lines.append("识别结果：当前未发现明显质量问题。")
                lines.append("建议：可直接保留原图。")
        else:
            lines.append("")
            lines.append("识别结果：尚未分析。")
        self._set_summary("\n".join(lines))

    def _set_meta_summary(self, text: str) -> None:
        self.meta_text.config(state="normal")
        self.meta_text.delete("1.0", "end")
        self.meta_text.insert("1.0", text)
        self.meta_text.config(state="disabled")

    def _update_hud(self, path: Path, image: Image.Image | None, result: AnalysisResult | None, error: str | None) -> None:
        if image is None:
            self.hud_name_var.set(path.name)
        else:
            try:
                self.hud_name_var.set(f"{path.name}  |  {image.width} x {image.height}")
            except Exception:
                self.hud_name_var.set(path.name)
        if error:
            self.hud_risk_var.set("风险值 --")
            self.hud_tags_var.set(f"识别结果：分析失败 - {error}")
            self.hud_methods_var.set("推荐修复：请先确认图片能正常读取")
            return
        if result is None:
            self.hud_risk_var.set("风险值 --")
            self.hud_tags_var.set("识别结果：尚未分析")
            self.hud_methods_var.set("推荐修复：等待分析完成")
            return
        self.hud_risk_var.set(f"风险值 {result.overall_score:.2f}")
        if result.issues:
            tags = "、".join(issue.label for issue in result.issues[:4])
            methods = "、".join(get_method_labels(suggest_methods_for_result(result))) or "暂无明确推荐"
            face_info = f" | raw/valid/reject {result.raw_face_count}/{result.validated_face_count}/{result.rejected_face_count}" if (result.raw_face_count or result.validated_face_count or result.rejected_face_count) else ""
            cleanup_hint = " | 建议删除候选" if result.cleanup_candidates else ""
            self.hud_tags_var.set(f"识别结果：{tags}{face_info}{cleanup_hint}")
            if result.cleanup_candidates:
                primary_cleanup = sorted(
                    result.cleanup_candidates,
                    key=lambda candidate: (self._cleanup_severity_rank(candidate.severity), candidate.confidence),
                    reverse=True,
                )[0]
                self.hud_methods_var.set(
                    f"推荐修复：{methods} | 清理建议：{primary_cleanup.reason_code} ({primary_cleanup.severity})"
                )
            else:
                self.hud_methods_var.set(f"推荐修复：{methods}")
        else:
            portrait_hint = f" | {result.portrait_scene_type}" if result.portrait_likely and result.portrait_scene_type else ""
            self.hud_tags_var.set(f"识别结果：未发现明显问题{portrait_hint}")
            if result.portrait_rejection_reason:
                self.hud_methods_var.set(f"推荐修复：未启用人像策略，{result.portrait_rejection_reason}")
            else:
                self.hud_methods_var.set("推荐修复：可保留原图，无需额外修正")

    def _set_summary(self, text: str) -> None:
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", text)
        self.summary_text.config(state="disabled")

    def export_selected(self) -> None:
        cleanup_primary = self._primary_cleanup_candidates()
        chosen = [path for path, flag in self.cleanup_flags.items() if flag.get() and path in cleanup_primary]
        if not chosen:
            chosen = [path for path, flag in self.selected_flags.items() if flag.get()]
        if not chosen:
            messagebox.showinfo("提示", "当前没有勾选需要处理的图片。")
            return
        output = export_cleanup_list(chosen, self._resolve_base_folder())
        self._log_console(f"exported cleanup list: {output}")
        self.status_var.set(f"已导出清理清单：{output}")
        messagebox.showinfo("完成", f"已导出清理清单：\n{output}")

    def cleanup_selected_candidates(self) -> None:
        primary_candidates = self._primary_cleanup_candidates()
        chosen = [path for path, flag in self.cleanup_flags.items() if flag.get() and path in primary_candidates and path.exists()]
        if not chosen:
            self._update_cleanup_controls()
            return

        preview_lines = []
        for path in chosen[:5]:
            candidate = primary_candidates[path]
            preview_lines.append(f"- {path.name} | {candidate.reason_code} | {candidate.severity}")
        if len(chosen) > 5:
            preview_lines.append(f"... 另外 {len(chosen) - 5} 张")
        confirm = messagebox.askyesno(
            "确认安全清理",
            "将优先尝试移入系统回收站；若系统不支持，则移入项目内安全隔离目录 `_cleanup_candidates`。\n\n"
            f"本次共 {len(chosen)} 张：\n" + "\n".join(preview_lines) + "\n\n是否继续？",
        )
        if not confirm:
            return

        operation = safe_cleanup_paths(chosen, self._resolve_base_folder())
        for path in chosen:
            self._remove_path_from_list(path, refresh=False)

        self.image_paths = [path for path in self.image_paths if path.exists()]
        self.refresh_tree()

        self._log_console(f"cleanup candidates handled: mode={operation.mode} moved={operation.moved} destination={operation.destination_label}")
        if operation.mode == "recycle_bin":
            detail = f"已将 {operation.moved} 张图片移入系统回收站。"
        elif operation.mode == "mixed":
            detail = f"已处理 {operation.moved} 张图片：{operation.destination_label}"
        else:
            detail = f"系统回收站不可用，已将 {operation.moved} 张图片移入安全隔离目录：{operation.destination_label}"
        self.status_var.set(detail)
        messagebox.showinfo("完成", detail)

    def cleanup_selected(self) -> None:
        if self._primary_cleanup_candidates():
            if not any(flag.get() for flag in self.cleanup_flags.values()):
                messagebox.showinfo("提示", "请先在“不适合保留候选”框体中勾选需要清理的图片。")
                self._update_cleanup_controls()
                return
            self.cleanup_selected_candidates()
            return

        chosen = [path for path, flag in self.selected_flags.items() if flag.get() and path.exists()]
        if not chosen:
            messagebox.showinfo("提示", "当前没有勾选需要清理的图片。")
            return

        confirm = messagebox.askyesno(
            "确认安全清理",
            "将优先尝试移入系统回收站；若系统不支持，则移入项目内安全隔离目录 `_cleanup_candidates`。\n\n"
            f"本次共 {len(chosen)} 张，是否继续？",
        )
        if not confirm:
            return

        operation = safe_cleanup_paths(chosen, self._resolve_base_folder())
        for path in chosen:
            self._remove_path_from_list(path, refresh=False)

        self.image_paths = [path for path in self.image_paths if path.exists()]
        self.refresh_tree()
        self._log_console(f"cleanup moved: mode={operation.mode} moved={operation.moved} -> {operation.destination_label}")
        self.status_var.set(f"已安全清理 {operation.moved} 张图片：{operation.destination_label}")
        messagebox.showinfo("完成", f"已安全清理 {operation.moved} 张图片：\n{operation.destination_label}")
