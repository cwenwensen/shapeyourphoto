from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps

from analyzer import analyze_image
from app_settings import (
    ANALYSIS_CONCURRENCY_AUTO,
    ANALYSIS_CONCURRENCY_CUSTOM,
    ANALYSIS_CONCURRENCY_HIGH,
    ANALYSIS_CONCURRENCY_LOW,
    ANALYSIS_CONCURRENCY_MEDIUM,
    AnalysisWorkerPlan,
    AppSettings,
    GPU_ACCELERATION_OFF,
    REPAIR_SUMMARY_FILTER_ALL,
    REPAIR_SUMMARY_FILTER_DISCARD_RELATED,
    REPAIR_SUMMARY_FILTER_FAILED,
    REPAIR_SUMMARY_FILTER_FORCED_SAVED,
    REPAIR_SUMMARY_FILTER_FORCED_UNSAVED,
    REPAIR_SUMMARY_FILTER_REPAIRED,
    REPAIR_SUMMARY_FILTER_ROLLBACK_NOOP,
    REPAIR_SUMMARY_FILTER_SKIPPED,
    load_app_settings,
    resolve_analysis_worker_plan,
    save_app_settings,
    scan_mode_label,
)
from app_console import AppConsole
from app_metadata import APP_NAME, APP_VERSION
from cleanup_review_dialog import CleanupReviewEntry, show_cleanup_review_dialog
from debug_open_dialog import DebugOpenEntry, show_debug_open_dialog
from diagnostics_chart import DiagnosticsChart
from drag_drop import WindowsFileDropTarget
from file_actions import ScanResult, export_cleanup_list, safe_cleanup_paths, scan_image_paths_with_progress
from history_dialog import show_history_dialog
from gpu_accel import GPUBackendStatus, gpu_console_label, resolve_gpu_status
from metadata_utils import summarize_image_metadata
from models import AnalysisResult, CleanupCandidate, RepairRecord, RepairSelection, SimilarImageGroup
from preview_cache import ThumbnailCache
from progress_dialog import TaskProgressController
from repair_completion_dialog import RepairCompletionEntry, show_repair_completion_dialog
from repair_dialog import show_repair_dialog
from repair_engine import repair_image_file
from repair_planner import get_method_labels, get_repair_methods, suggest_methods_for_result, suggest_methods_for_results
from result_sorting import sort_paths
from scan_dialogs import (
    SCAN_MODE_ALL,
    show_scan_mode_dialog,
)
from scan_summary_dialog import show_scan_summary_dialog
from settings_dialog import show_app_settings_dialog
from similar_detector import detect_similar_groups
from similar_review_dialog import show_similar_group_decision_dialog, show_similar_group_list_dialog
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
DEFAULT_ANALYSIS_WORKERS = max(1, min(12, os.cpu_count() or 4))
DEFAULT_REPAIR_WORKERS = max(1, min(4, max(1, (os.cpu_count() or 4) // 2)))
ANALYSIS_TIMING_LABELS = [
    ("读取图片", ("image_read",)),
    ("打开文件", ("image_open",)),
    ("EXIF 方向归一", ("exif_transpose",)),
    ("色彩转换", ("image_convert",)),
    ("工作图缩放", ("resize", "working_resize")),
    ("数组转换", ("array_convert",)),
    ("基础统计", ("basic_stats",)),
    ("曝光", ("exposure",)),
    ("色彩", ("color",)),
    ("清晰度", ("sharpness",)),
    ("噪点", ("noise",)),
    ("场景判断", ("scene_classify",)),
    ("人像/清晰度/噪声/色彩判断", ("face_detect", "portrait_region_build", "quality_stats", "issue_build")),
    ("人像", ("face_detect", "portrait_region_build")),
    ("cleanup candidate", ("cleanup_candidate",)),
]
ANALYSIS_BATCH_TIMING_LABELS = ANALYSIS_TIMING_LABELS + [
    ("相似图检测", ("similar_detection",)),
    ("缩略图/预览/UI", ("thumbnail", "preview", "ui_refresh", "UI_update", "ui_update")),
    ("Console 刷新", ("console_flush",)),
]
REPAIR_TIMING_LABELS = [
    ("生成修复方案", ("planner",)),
    ("读取图片", ("image_read",)),
    ("执行修复步骤", ("candidate_generation", "op:auto_tone", "op:recover_highlights", "op:lift_shadows", "op:boost_contrast", "op:boost_vibrance", "op:reduce_saturation", "op:warm_up", "op:cool_down", "op:add_magenta", "op:add_green", "op:boost_clarity", "op:reduce_noise", "op:portrait_local_face_enhance", "op:portrait_subject_midcontrast", "op:portrait_dark_clothing_detail", "op:protect_high_key_background")),
    ("候选评分/安全检查", ("candidate_scoring", "mask_build", "mask_feather")),
    ("保存输出", ("save_output",)),
    ("元数据保留", ("metadata_preserve",)),
]


class AnalysisCanceled(Exception):
    pass


class PhotoAnalyzerApp:
    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.root.geometry("1700x1020")
        self.root.minsize(1380, 880)

        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择图片目录开始分析。")
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
        self.similar_groups: list[SimilarImageGroup] = []
        self.item_lookup: dict[str, Path] = {}
        self.path_item_lookup: dict[Path, str] = {}
        self.cleanup_item_lookup: dict[str, Path] = {}
        self.worker_lock = threading.Lock()
        self.is_busy = False
        self.control_widgets: list[ttk.Widget] = []
        self.thumb_cache = ThumbnailCache()
        self.list_menu: tk.Menu | None = None
        self.stats = load_stats()
        self.console = AppConsole()
        self._console_update_pending = False
        self._last_progress_ui_update = 0.0
        self._last_repair_phase_update = 0.0
        self._settings_warnings: list[str] = []
        self.settings: AppSettings = load_app_settings(report_warning=self._settings_warnings.append, create_if_missing=True)
        self.drop_target: WindowsFileDropTarget | None = None
        self.sort_column = "name"
        self.sort_reverse = False
        self.analysis_phase_progress: dict[Path, int] = {}
        self._last_scan_update = 0.0
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._last_analysis_targets: list[Path] = []
        self._analysis_run_id = 0
        self._analysis_cancel_event: threading.Event | None = None
        self._analysis_cancel_targets: list[Path] = []
        self._task_started_at = 0.0
        self._last_scan_summary: str = ""
        self._last_scan_results: list[ScanResult] = []
        self._auto_analyze_after_scan = False
        self._console_flush_total_ms = 0.0
        self._console_flush_count = 0

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
        for warning in self._settings_warnings:
            self._log_console(warning)
        self._log_console(f"scan ignore prefixes: {', '.join(self.settings.scan_ignore_prefixes)}")

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
        review_menu.add_command(label="打开相似图片组", command=self.open_similar_group_window)
        review_menu.add_command(label="最近扫描摘要", command=self.show_last_scan_summary)
        menu_bar.add_cascade(label="查看", menu=review_menu)
        settings_menu = tk.Menu(menu_bar, tearoff=False)
        settings_menu.add_command(label="应用设置", command=self.open_settings_panel)
        menu_bar.add_cascade(label="设置", menu=settings_menu)
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
            text="读取目录",
            style="Soft.TButton",
            command=self.scan_folder,
        )
        analyze_all_button = ttk.Button(controls, text="分析全部", style="Accent.TButton", command=self.analyze_all)
        analyze_selected_button = ttk.Button(controls, text="分析选中", command=self.analyze_selected)
        repair_current_button = ttk.Button(controls, text="修复当前", command=self.repair_current)
        repair_checked_button = ttk.Button(controls, text="批量修复勾选", command=self.repair_checked)
        stats_button = ttk.Button(controls, text="累计统计", command=self.show_stats)
        history_button = ttk.Button(controls, text="更新历史", command=lambda: show_history_dialog(self.root))
        export_button = ttk.Button(controls, text="导出清理清单", command=self.export_selected)
        cleanup_button = ttk.Button(controls, text="清理勾选项", command=self.cleanup_selected)

        button_specs: list[ttk.Button] = []
        button_specs.append(choose_folder_button)
        button_specs.extend(
            [
                choose_image_button,
                scan_button,
                analyze_all_button,
                analyze_selected_button,
                repair_current_button,
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
        self.scan_summary_button = ttk.Button(
            progress_panel,
            text="查看最近扫描摘要",
            command=self.show_last_scan_summary,
            state="disabled",
        )
        self.scan_summary_button.pack(anchor="e", pady=(8, 0))

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

        def _schedule_flush() -> None:
            if self._console_update_pending:
                return
            self._console_update_pending = True
            self.root.after(120, self._flush_console)

        if threading.current_thread() is threading.main_thread():
            _schedule_flush()
        else:
            self._dispatch_ui(_schedule_flush)

    def _flush_console(self) -> None:
        self._console_update_pending = False
        if not hasattr(self, "console_text"):
            return
        started_at = time.perf_counter()
        try:
            self.console_text.config(state="normal")
            self.console_text.delete("1.0", "end")
            self.console_text.insert("1.0", self.console.dump())
            self.console_text.config(state="disabled")
            self.console_text.see("end")
        except tk.TclError:
            return
        self._console_flush_total_ms += (time.perf_counter() - started_at) * 1000.0
        self._console_flush_count += 1

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
        scan_requests: list[tuple[Path, str]] = []
        for item in dropped:
            if item.is_dir():
                plan = self._resolve_scan_plan(item)
                if plan is None:
                    continue
                scan_requests.append((item, plan))
            elif item.is_file():
                image_paths.append(item)
        if scan_requests:
            self.folder_var.set(str(scan_requests[0][0]))
            self._start_directory_scans(scan_requests, initial_paths=image_paths, origin="drag_drop")
            return
        if not image_paths:
            self._log_console("drag drop ignored: no supported image or scan canceled")
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

    def scan_folder(self) -> None:
        if self.is_busy:
            self._auto_analyze_after_scan = False
            messagebox.showinfo("提示", "当前有任务正在运行，请稍后。")
            return

        folder = self.folder_var.get().strip()
        if not folder:
            self._auto_analyze_after_scan = False
            messagebox.showwarning("提示", "请先选择图片目录。")
            return

        root = Path(folder)
        if not root.exists():
            self._auto_analyze_after_scan = False
            messagebox.showerror("错误", "目录不存在，请重新选择。")
            return

        scan_mode = self._resolve_scan_plan(root)
        if scan_mode is None:
            self._auto_analyze_after_scan = False
            self._log_console(f"scan canceled: {root}")
            return
        self._start_directory_scans([(root, scan_mode)], origin="button")

    def analyze_all(self) -> None:
        if not self.image_paths:
            self._auto_analyze_after_scan = True
            self.scan_folder()
            return
        self._auto_analyze_after_scan = False
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

    def show_stats(self) -> None:
        show_stats_dialog(self.root, self.stats)

    def open_settings_panel(self) -> None:
        settings = show_app_settings_dialog(self.root, self.settings)
        if settings is None:
            return
        try:
            save_app_settings(settings, report_warning=lambda message: self._log_console(message))
        except Exception as exc:
            messagebox.showerror("保存失败", f"应用设置保存失败：\n{exc}")
            self._log_console(f"settings save failed: {exc}")
            return
        self.settings = settings
        self.status_var.set("应用设置已保存，新的扫描和修复详情窗口会立即使用最新配置。")
        self._log_console(
            "settings updated: "
            f"ignore={','.join(self.settings.scan_ignore_prefixes)} | "
            f"default_scan={self.settings.default_scan_mode} | "
            f"repair_summary_filter={self.settings.repair_summary_default_filter} | "
            f"analysis_concurrency={self.settings.analysis_concurrency_mode}:{self.settings.analysis_custom_workers or 'auto'} | "
            f"gpu={self.settings.gpu_acceleration_mode}"
        )

    def show_last_scan_summary(self) -> None:
        if not self._last_scan_results:
            messagebox.showinfo("提示", "当前还没有可查看的扫描摘要。")
            return
        show_scan_summary_dialog(self.root, self._last_scan_results)

    def _resolve_scan_plan(self, root: Path) -> str | None:
        has_subdirs = any(child.is_dir() for child in root.iterdir())
        if not has_subdirs:
            return SCAN_MODE_ALL
        if self.settings.default_scan_mode != "ask":
            return self.settings.default_scan_mode
        return show_scan_mode_dialog(self.root, root, self.settings.scan_ignore_prefixes)

    def _scan_mode_label(self, mode: str) -> str:
        return scan_mode_label(mode)

    def _start_directory_scans(
        self,
        scan_requests: list[tuple[Path, str]],
        *,
        initial_paths: list[Path] | None = None,
        origin: str,
    ) -> None:
        requests = [(root, mode) for root, mode in scan_requests if root.exists()]
        initial = [path for path in (initial_paths or []) if path.exists()]
        if not requests and initial:
            self._merge_paths(initial)
            self.thumb_cache.clear()
            self.refresh_tree()
            self._select_path(initial[0])
            self._log_console(f"drag drop added: {len(initial)} image(s)")
            return
        if not requests:
            return

        self._last_scan_update = 0.0
        self._begin_task(
            1,
            "读取目录 0/0",
            f"正在扫描目录：{requests[0][0]}",
            show_dialog=True,
            dialog_title="读取目录中",
            dialog_header="正在扫描目录文件",
        )
        for root, mode in requests:
            self._log_console(
                f"scan started: root={root} mode={self._scan_mode_label(mode)} ignore={','.join(self.settings.scan_ignore_prefixes)} origin={origin}"
            )

        def worker() -> None:
            merged_paths = list(initial)
            scan_results: list[ScanResult] = []
            try:
                for root, mode in requests:
                    def progress_callback(done: int, total: int, found: int, current: Path | None, scan_root: Path = root, scan_mode: str = mode) -> None:
                        current_label = "准备扫描..."
                        if current is not None:
                            try:
                                current_label = str(current.relative_to(scan_root))
                            except ValueError:
                                current_label = current.name
                        prefix = f"{scan_root.name} | {self._scan_mode_label(scan_mode)}"
                        self._dispatch_ui(
                            lambda d=done, t=total, f=found, label=f"{prefix} | {current_label}": self._update_scan_progress(d, t, f, label)
                        )

                    scan_result = scan_image_paths_with_progress(
                        root,
                        progress_callback,
                        mode=mode,
                        ignored_dir_prefixes=self.settings.scan_ignore_prefixes,
                    )
                    merged_paths.extend(scan_result.paths)
                    scan_results.append(scan_result)
                    self._log_scan_console_summary(scan_result)
            except Exception as exc:
                self._dispatch_ui(lambda: self._scan_failed(str(exc)))
                return
            self._dispatch_ui(lambda paths=merged_paths, results=scan_results: self._scan_finished(paths, results))

        threading.Thread(target=worker, daemon=True).start()

    def _format_scan_summary(self, scan_result: ScanResult) -> str:
        summary = scan_result.summary
        prefix_counts = summary.skipped_prefix_counts
        prefix_text = "；".join(f"{prefix}：{count} 个" for prefix, count in prefix_counts.items()) if prefix_counts else "无"
        return (
            f"[{summary.root.name}] 扫描模式：{self._scan_mode_label(summary.mode)} | "
            f"跳过目录 {summary.skipped_directory_count} 个 | "
            f"导入图片 {summary.imported_count} 张 | "
            f"命中前缀：{prefix_text}"
        )

    def _log_scan_console_summary(self, scan_result: ScanResult) -> None:
        summary = scan_result.summary
        prefix_counts = summary.skipped_prefix_counts
        if prefix_counts:
            prefix_text = "；".join(f"{prefix}:{count}" for prefix, count in prefix_counts.items())
            self._log_console(
                f"scan skipped summary: root={summary.root} skipped={summary.skipped_directory_count} prefixes={prefix_text}"
            )
            for detail in summary.skipped_details[:5]:
                try:
                    label = str(detail.path.relative_to(summary.root))
                except ValueError:
                    label = detail.path.name
                self._log_console(f"已跳过目录：{label} | prefix={detail.matched_prefix}")
            if summary.skipped_directory_count > 5:
                self._log_console(f"更多跳过目录明细请在“最近扫描摘要”中查看，共 {summary.skipped_directory_count} 个。")
        else:
            self._log_console(f"scan skipped summary: root={summary.root} skipped=0")

    def _analysis_worker_plan(self, total: int) -> AnalysisWorkerPlan:
        return resolve_analysis_worker_plan(
            total,
            getattr(self.settings, "analysis_concurrency_mode", ANALYSIS_CONCURRENCY_AUTO),
            getattr(self.settings, "analysis_custom_workers", 0),
        )

    def _analysis_workers(self, total: int) -> int:
        return self._analysis_worker_plan(total).actual_workers

    def _analysis_concurrency_label(self, plan: AnalysisWorkerPlan | int) -> str:
        if isinstance(plan, int):
            plan = AnalysisWorkerPlan(
                mode=getattr(self.settings, "analysis_concurrency_mode", ANALYSIS_CONCURRENCY_AUTO),
                requested_workers=plan,
                actual_workers=plan,
            )
        detail = f"ThreadPool setting={plan.mode} requested={plan.requested_workers} actual={plan.actual_workers}"
        if plan.reason:
            detail += f" ({plan.reason})"
        return detail

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
        self._prune_similar_groups()

    def _prune_similar_groups(self) -> None:
        kept: list[SimilarImageGroup] = []
        next_id = 1
        for group in self.similar_groups:
            group.paths[:] = [path for path in group.paths if path.exists() and path in self.image_paths]
            if len(group.paths) < 2:
                continue
            group.group_id = next_id
            kept.append(group)
            next_id += 1
        self.similar_groups = kept

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
        cancel_callback=None,
        cancel_text: str = "取消",
    ) -> None:
        self._task_started_at = time.monotonic()
        self._last_progress_ui_update = 0.0
        self._last_repair_phase_update = 0.0
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
            cancel_callback=cancel_callback,
            cancel_text=cancel_text,
        )

    def _finish_task(self, title: str, detail: str) -> None:
        self.is_busy = False
        self._set_controls_enabled(True)
        self.progress_controller.finish(title=title, detail=detail, status=detail, close_dialog=True)
        self._flush_console()

    def _elapsed_task_text(self) -> str:
        seconds = max(0, int(time.monotonic() - self._task_started_at)) if self._task_started_at else 0
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"耗时 {hours:02d}:{minutes:02d}:{sec:02d}"
        return f"耗时 {minutes:02d}:{sec:02d}"

    def _format_ms(self, value: float) -> str:
        if value >= 1000.0:
            return f"{value / 1000.0:.2f}s"
        return f"{value:.0f}ms"

    def _sum_timings(self, timings: dict[str, float], keys: tuple[str, ...]) -> float:
        return sum(float(timings.get(key, 0.0)) for key in keys)

    def _format_timing_parts(self, timings: dict[str, float], labels: list[tuple[str, tuple[str, ...]]]) -> str:
        parts = []
        for label, keys in labels:
            value = self._sum_timings(timings, keys)
            if value > 0.0:
                parts.append(f"{label} {self._format_ms(value)}")
        return " | ".join(parts) if parts else "暂无阶段耗时"

    def _slowest_stage(self, timings: dict[str, float], labels: list[tuple[str, tuple[str, ...]]]) -> tuple[str, float]:
        candidates = [(label, self._sum_timings(timings, keys)) for label, keys in labels]
        return max(candidates, key=lambda item: item[1], default=("未记录", 0.0))

    def _top_stage_totals(
        self,
        records: list[AnalysisResult] | list[RepairRecord],
        labels: list[tuple[str, tuple[str, ...]]],
        *,
        extra_timings: dict[str, float] | None = None,
        limit: int = 5,
    ) -> list[tuple[str, float]]:
        totals: dict[str, float] = {}
        for record in records:
            timings = getattr(record, "perf_timings", {})
            for label, keys in labels:
                totals[label] = totals.get(label, 0.0) + self._sum_timings(timings, keys)
        if extra_timings:
            for label, keys in labels:
                totals[label] = totals.get(label, 0.0) + self._sum_timings(extra_timings, keys)
        return [(label, value) for label, value in sorted(totals.items(), key=lambda item: item[1], reverse=True) if value > 0.0][:limit]

    def _format_analysis_perf_line(self, result: AnalysisResult, ui_ms: float) -> str:
        timings = dict(result.perf_timings)
        timings["ui_refresh"] = ui_ms
        parts = self._format_timing_parts(timings, ANALYSIS_TIMING_LABELS + [("UI 刷新", ("ui_refresh",))])
        total = timings.get("analyze_total", 0.0)
        return f"analysis timing: {result.path.name} | total {self._format_ms(total)} | {parts}"

    def _format_repair_perf_line(self, record: RepairRecord) -> str:
        parts = self._format_timing_parts(record.perf_timings, REPAIR_TIMING_LABELS)
        total = record.perf_timings.get("repair_total", 0.0)
        return f"repair timing: {record.source_path.name} | total {self._format_ms(total)} | {parts}"

    def _log_analysis_perf_rollup(
        self,
        paths: list[Path],
        batch_timings: dict[str, float],
        *,
        total: int,
        success: int,
        failed: int,
        canceled: int,
        worker_plan: AnalysisWorkerPlan,
        gpu_status: GPUBackendStatus,
    ) -> None:
        records = [self.results[path] for path in paths if path in self.results]
        batch_timings["console_flush"] = self._console_flush_total_ms
        batch_timings["UI_update"] = sum(record.perf_timings.get("UI_update", 0.0) for record in records)
        wall_ms = batch_timings.get("wall_time", batch_timings.get("total_wall_time", 0.0))
        worker_cumulative_ms = batch_timings.get(
            "worker_cumulative_time",
            sum(record.perf_timings.get("worker_wall_time", record.perf_timings.get("analyze_total", 0.0)) for record in records),
        )
        analyze_cumulative_ms = batch_timings.get(
            "analyze_cumulative_time",
            sum(record.perf_timings.get("analyze_total", 0.0) for record in records),
        )
        queue_wait_ms = batch_timings.get("queue_wait_cumulative", batch_timings.get("queue_wait", 0.0))
        avg_wall_ms = wall_ms / max(1, total)
        avg_worker_ms = worker_cumulative_ms / max(1, len(records))
        parallel_factor = worker_cumulative_ms / max(1.0, wall_ms)
        if not records:
            self._log_console(
                f"本轮分析完成：{total} 张，成功 {success}，失败 {failed}，取消 {canceled} | "
                f"本轮分析真实耗时 {self._format_ms(wall_ms)} | "
                f"并发模式 {self._analysis_concurrency_label(worker_plan)} | CPU/GPU {gpu_console_label(gpu_status)}"
            )
            return
        self._log_console(
            f"本轮分析完成：{total} 张，成功 {success}，失败 {failed}，取消 {canceled} | "
            f"本轮分析真实耗时 {self._format_ms(wall_ms)} | 平均真实等待折算 {self._format_ms(avg_wall_ms)}/张 | "
            f"并发模式 {self._analysis_concurrency_label(worker_plan)} | "
            f"CPU/GPU {gpu_console_label(gpu_status)}"
        )
        self._log_console(
            f"analysis audit: wall_time={self._format_ms(wall_ms)} | "
            f"worker_cumulative_time={self._format_ms(worker_cumulative_ms)}（并发 worker 单图耗时累计，不是用户等待时间） | "
            f"analyze_cumulative_time={self._format_ms(analyze_cumulative_ms)} | "
            f"average_wall_time_per_image={self._format_ms(avg_wall_ms)} | "
            f"average_worker_time_per_image={self._format_ms(avg_worker_ms)} | "
            f"parallel_efficiency={parallel_factor:.2f}x | "
            f"queue/wait_cumulative={self._format_ms(queue_wait_ms)} | "
            f"similar_detection={self._format_ms(batch_timings.get('similar_detection', 0.0))} | "
            f"UI_update={self._format_ms(batch_timings.get('UI_update', 0.0))} | "
            f"console_flush={self._format_ms(batch_timings.get('console_flush', 0.0))}/{self._console_flush_count}次"
        )
        for record in sorted(records, key=lambda item: item.perf_timings.get("analyze_total", 0.0), reverse=True)[:5]:
            stage, stage_ms = self._slowest_stage(record.perf_timings, ANALYSIS_TIMING_LABELS)
            self._log_console(
                f"analysis slow image: {record.path.name} | total={self._format_ms(record.perf_timings.get('analyze_total', 0.0))} "
                f"| slowest={stage} {self._format_ms(stage_ms)}"
            )
        top_stages = self._top_stage_totals(records, ANALYSIS_BATCH_TIMING_LABELS, extra_timings=batch_timings, limit=5)
        if top_stages:
            self._log_console(
                "analysis slow stages top5: "
                + " | ".join(f"{label} {self._format_ms(value)}" for label, value in top_stages)
            )
        wall_ms = max(1.0, wall_ms)
        ui_console_ms = batch_timings.get("UI_update", 0.0) + batch_timings.get("console_flush", 0.0)
        similar_ms = batch_timings.get("similar_detection", 0.0)
        notes: list[str] = []
        if parallel_factor < max(1.0, worker_plan.actual_workers * 0.35) and len(records) >= worker_plan.actual_workers:
            notes.append("worker 并行度偏低，可能受磁盘 IO、Python/GIL 阶段或主线程刷新牵制")
        if ui_console_ms >= wall_ms * 0.18:
            notes.append("UI/Console 刷新占比较高")
        if similar_ms >= wall_ms * 0.20:
            notes.append("相似图检测占比较高")
        if queue_wait_ms >= wall_ms * 0.35:
            notes.append("排队等待较多，可考虑提高并发或减少单张分析耗时")
        if not notes:
            notes.append("本轮主要耗时集中在 worker 图像分析阶段")
        self._log_console("analysis bottleneck notes: " + "；".join(notes))

    def _log_repair_perf_rollup(self, records: list[RepairRecord]) -> None:
        if not records:
            return
        totals = [record.perf_timings.get("repair_total", 0.0) for record in records if record.perf_timings]
        if not totals:
            return
        total_ms = sum(totals)
        avg_ms = total_ms / max(1, len(totals))
        saved = sum(1 for record in records if record.saved_output)
        skipped = sum(1 for record in records if not record.saved_output)
        rollback_noop = sum(1 for record in records if record.outcome_category in {"forced_rollback", "normal_skipped"} or "rollback" in record.outcome_category or "noop" in record.outcome_category)
        self._log_console(
            f"本轮修复总耗时：{self._format_ms(total_ms)} | 平均每张 {self._format_ms(avg_ms)} | "
            f"保存 {saved}，跳过 {skipped}，回退/no-op {rollback_noop}"
        )
        for record in sorted(records, key=lambda item: item.perf_timings.get("repair_total", 0.0), reverse=True)[:5]:
            stage, stage_ms = self._slowest_stage(record.perf_timings, REPAIR_TIMING_LABELS)
            self._log_console(
                f"repair slow image: {record.source_path.name} | total={self._format_ms(record.perf_timings.get('repair_total', 0.0))} "
                f"| slowest={stage} {self._format_ms(stage_ms)}"
            )
        top_stages = self._top_stage_totals(records, REPAIR_TIMING_LABELS, limit=5)
        if top_stages:
            self._log_console(
                "repair slow stages top5: "
                + " | ".join(f"{label} {self._format_ms(value)}" for label, value in top_stages)
            )

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

    def _scan_finished(self, paths: list[Path], scan_results: list[ScanResult]) -> None:
        self._merge_paths(paths)
        self.thumb_cache.clear()
        self.progress_bar.configure(maximum=max(1, len(self.image_paths)))
        self.progress_value.set(0.0)
        self._last_scan_results = list(scan_results)
        self.scan_summary_button.configure(state="normal" if self._last_scan_results else "disabled")
        summary_lines = [self._format_scan_summary(result) for result in scan_results]
        self._last_scan_summary = "；".join(summary_lines)
        for line in summary_lines:
            self._log_console(f"scan summary: {line}")
        self._log_console(f"scan finished: new={len(paths)} total={len(self.image_paths)}")
        detail = f"当前列表共 {len(self.image_paths)} 张图片，本次新读取 {len(paths)} 张。"
        if self._last_scan_summary:
            detail = f"{detail}\n{self._last_scan_summary}\n可点击“查看最近扫描摘要”查看跳过目录明细。"
        self._finish_task("目录读取完成", detail)
        self.refresh_tree()
        if self.image_paths:
            self._select_path(self.image_paths[0])
        if self._auto_analyze_after_scan and self.image_paths:
            self._auto_analyze_after_scan = False
            self._run_analysis(self.image_paths)
        else:
            self._auto_analyze_after_scan = False

    def _scan_failed(self, error: str) -> None:
        self._auto_analyze_after_scan = False
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
        self._analysis_run_id += 1
        run_id = self._analysis_run_id
        cancel_event = threading.Event()
        self._analysis_cancel_event = cancel_event
        self._analysis_cancel_targets = list(targets)
        self.analysis_phase_progress = {path: 0 for path in targets}
        self._last_analysis_targets = list(targets)
        worker_plan = self._analysis_worker_plan(total)
        worker_count = worker_plan.actual_workers
        gpu_status = resolve_gpu_status(getattr(self.settings, "gpu_acceleration_mode", GPU_ACCELERATION_OFF))
        self._console_flush_total_ms = 0.0
        self._console_flush_count = 0

        self._log_console(
            f"analysis started: count={total} mode={self._analysis_concurrency_label(worker_plan)} "
            f"gpu={gpu_console_label(gpu_status)}"
        )
        self._log_console(gpu_status.reason)
        self._begin_task(
            total * ANALYSIS_PROGRESS_STEPS,
            f"分析中 0/{total}",
            f"正在分析 {total} 张图片，请稍候...",
            show_dialog=True,
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
            cancel_callback=lambda rid=run_id: self.cancel_analysis(rid),
            cancel_text="取消分析",
        )

        for path in targets:
            self.results.pop(path, None)
            self.errors.pop(path, None)
            self.cleanup_flags.pop(path, None)
        target_set = set(targets)
        self.similar_groups = [
            group for group in self.similar_groups if not any(path in target_set for path in group.paths)
        ]
        self.refresh_tree()
        current = self._current_path()
        if current in targets:
            self.show_preview(current)

        def worker() -> None:
            done = 0
            batch_results: dict[Path, AnalysisResult] = {}
            batch_timings: dict[str, float] = {}
            batch_started_at = time.perf_counter()
            pool = ThreadPoolExecutor(max_workers=worker_count)
            futures = {}
            try:
                for path in targets:
                    if cancel_event.is_set():
                        break

                    def progress_callback(step: int, steps: int, phase: str, p: Path = path) -> None:
                        if cancel_event.is_set():
                            raise AnalysisCanceled("analysis canceled")
                        self._dispatch_ui(
                            lambda p=p, step=step, steps=steps, phase=phase, rid=run_id: self._update_analysis_phase(
                                p, step, steps, phase, total, rid
                            )
                        )

                    queued_at = time.perf_counter()

                    def analyze_job(p: Path = path, queued: float = queued_at, cb=progress_callback):
                        started = time.perf_counter()
                        result = analyze_image(p, cb)
                        finished = time.perf_counter()
                        result.perf_timings["worker_queue_wait"] = (started - queued) * 1000.0
                        result.perf_timings["worker_wall_time"] = (finished - started) * 1000.0
                        return result

                    futures[pool.submit(analyze_job)] = path

                for future in as_completed(futures):
                    path = futures[future]
                    if cancel_event.is_set():
                        break
                    result: AnalysisResult | None = None
                    error: str | None = None
                    try:
                        result = future.result()
                    except AnalysisCanceled:
                        cancel_event.set()
                        break
                    except Exception as exc:
                        error = str(exc)
                    if result is not None:
                        batch_results[path] = result
                    done += 1
                    self._dispatch_ui(
                        lambda p=path, r=result, e=error, d=done, t=total, rid=run_id: self._handle_analysis_item_done(
                            p, r, e, d, t, rid
                        )
                    )
            finally:
                if cancel_event.is_set():
                    shutdown_started_at = time.perf_counter()
                    for future in futures:
                        future.cancel()
                    pool.shutdown(wait=True, cancel_futures=True)
                    shutdown_ms = (time.perf_counter() - shutdown_started_at) * 1000.0
                    elapsed_ms = (time.perf_counter() - batch_started_at) * 1000.0
                    submitted = len(futures)
                    discarded_results = len(batch_results)
                    canceled_or_pending = max(0, total - done)
                    self._dispatch_ui(
                        lambda rid=run_id, elapsed=elapsed_ms, shutdown=shutdown_ms, sub=submitted, completed=done,
                        discarded=discarded_results, canceled=canceled_or_pending: self._analysis_cancel_worker_finished(
                            rid,
                            total=total,
                            elapsed_ms=elapsed,
                            shutdown_ms=shutdown,
                            submitted=sub,
                            completed=completed,
                            discarded_results=discarded,
                            canceled_or_pending=canceled,
                        )
                    )
                else:
                    pool.shutdown(wait=True)

            if not cancel_event.is_set():
                self._dispatch_ui(lambda rid=run_id, t=total: self._update_similarity_detection_phase(t, rid))
                similar_started_at = time.perf_counter()
                similar_groups = detect_similar_groups(
                    targets,
                    batch_results,
                    max_workers=worker_count,
                    perf_timings=batch_timings,
                )
                similar_ms = (time.perf_counter() - similar_started_at) * 1000.0
                batch_timings["similar_detection"] = max(batch_timings.get("similar_detection", 0.0), similar_ms)
                batch_timings["wall_time"] = (time.perf_counter() - batch_started_at) * 1000.0
                batch_timings["total_wall_time"] = batch_timings["wall_time"]
                batch_timings["worker_cumulative_time"] = sum(
                    result.perf_timings.get("worker_wall_time", result.perf_timings.get("analyze_total", 0.0))
                    for result in batch_results.values()
                )
                batch_timings["total_worker_time"] = batch_timings["worker_cumulative_time"]
                batch_timings["analyze_cumulative_time"] = sum(result.perf_timings.get("analyze_total", 0.0) for result in batch_results.values())
                batch_timings["average_wall_time_per_image"] = batch_timings["wall_time"] / max(1, total)
                batch_timings["average_worker_time_per_image"] = batch_timings["worker_cumulative_time"] / max(1, len(batch_results))
                batch_timings["queue_wait_cumulative"] = sum(result.perf_timings.get("worker_queue_wait", 0.0) for result in batch_results.values())
                batch_timings["queue_wait"] = batch_timings["queue_wait_cumulative"]
                self._dispatch_ui(
                    lambda rid=run_id, groups=similar_groups, timings=batch_timings: self._analysis_finished(
                        total,
                        rid,
                        groups,
                        timings,
                        worker_plan,
                        gpu_status,
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

    def cancel_analysis(self, run_id: int | None = None) -> None:
        if run_id is not None and run_id != self._analysis_run_id:
            return
        canceled_run_id = self._analysis_run_id
        cancel_event = self._analysis_cancel_event
        if cancel_event is not None:
            cancel_event.set()
        self._analysis_run_id += 1
        targets = list(self._analysis_cancel_targets or self._last_analysis_targets)
        cleared_results = sum(1 for path in targets if path in self.results)
        cleared_errors = sum(1 for path in targets if path in self.errors)
        for path in targets:
            self.results.pop(path, None)
            self.errors.pop(path, None)
            self.cleanup_flags.pop(path, None)
            self.analysis_phase_progress[path] = 0
        target_set = set(targets)
        self.similar_groups = [
            group for group in self.similar_groups if not any(path in target_set for path in group.paths)
        ]
        self.analysis_phase_progress = {}
        self._last_analysis_targets = []
        self._analysis_cancel_targets = []
        self._analysis_cancel_event = None
        detail = f"已取消本轮分析，{len(targets)} 张图片保留在列表中，可重新点击“分析全部”。"
        elapsed_ms = max(0.0, (time.monotonic() - self._task_started_at) * 1000.0) if self._task_started_at else 0.0
        self._log_console(
            f"analysis cancel requested: run={canceled_run_id} | elapsed={self._format_ms(elapsed_ms)} | "
            f"targets={len(targets)} | cleared_results={cleared_results} | cleared_errors={cleared_errors} | "
            f"canceled={len(targets)}"
        )
        self.is_busy = False
        self._set_controls_enabled(True)
        self.progress_controller.finish(title="分析已取消", detail=detail, status=detail, close_dialog=True)
        self._flush_console()
        self.refresh_tree()
        current = self._current_path()
        if current is not None:
            self.show_preview(current)
        elif targets:
            self._select_path(targets[0])

    def _analysis_cancel_worker_finished(
        self,
        run_id: int,
        *,
        total: int,
        elapsed_ms: float,
        shutdown_ms: float,
        submitted: int,
        completed: int,
        discarded_results: int,
        canceled_or_pending: int,
    ) -> None:
        self._log_console(
            f"analysis cancel confirmed: run={run_id} | wall={self._format_ms(elapsed_ms)} | "
            f"submitted={submitted}/{total} | completed_before_stop={completed} | "
            f"discarded_results={discarded_results} | canceled_or_pending={canceled_or_pending} | "
            f"worker_shutdown_wait={self._format_ms(shutdown_ms)}"
        )

    def _handle_analysis_item_done(
        self,
        path: Path,
        result: AnalysisResult | None,
        error: str | None,
        done: int,
        total: int,
        run_id: int,
    ) -> None:
        if run_id != self._analysis_run_id or (self._analysis_cancel_event is not None and self._analysis_cancel_event.is_set()):
            return
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

        ui_started_at = time.perf_counter()
        self.progress_controller.update(
            done=sum(self.analysis_phase_progress.values()),
            total=total * ANALYSIS_PROGRESS_STEPS,
            title=f"分析中 {done}/{total}",
            detail=f"已完成第 {done}/{total} 张：{path.name} | 生成建议与诊断信息 | {self._elapsed_task_text()}",
            status=f"分析进度 {done}/{total}，最近完成：{path.name}",
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
        )
        if not self._refresh_tree_item(path):
            self.refresh_tree()
        self._refresh_cleanup_tree()
        current = self._current_path()
        if current is None:
            self._select_path(path)
        elif current == path:
            self.show_preview(path)
        if result is not None:
            ui_ms = (time.perf_counter() - ui_started_at) * 1000.0
            result.perf_timings["UI_update"] = result.perf_timings.get("UI_update", 0.0) + ui_ms
            self._log_console(self._format_analysis_perf_line(result, ui_ms))

    def _run_repair(self, targets: list[Path], selection: RepairSelection) -> None:
        if self.is_busy:
            messagebox.showinfo("提示", "当前已有任务正在运行。")
            return

        missing = [path for path in targets if path not in self.results and path not in self.errors]
        total_steps = len(missing) + len(targets)
        analysis_worker_plan = self._analysis_worker_plan(len(missing)) if missing else None
        analysis_workers = analysis_worker_plan.actual_workers if analysis_worker_plan is not None else 0
        repair_workers = self._repair_workers(len(targets))
        self._log_console(
            f"repair started: count={len(targets)} pre_analyze={len(missing)} mode={selection.mode} overwrite={selection.overwrite_original} "
            f"analysis_workers={self._analysis_concurrency_label(analysis_worker_plan) if analysis_worker_plan else 0} repair_workers={repair_workers}"
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
                    def repair_progress(phase: str, p: Path = path) -> None:
                        self._dispatch_ui(
                            lambda s=step, t=total_steps, name=p.name, phase=phase: self._update_repair_phase(
                                s, t, name, phase
                            )
                        )

                    futures[
                        pool.submit(
                            repair_image_file,
                            path,
                            self.results.get(path),
                            selection,
                            self._resolve_base_folder(),
                            repair_progress,
                        )
                    ] = path

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
                            self._log_console(self._format_repair_perf_line(record))

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
        friendly_phase = self._friendly_repair_phase(phase)
        self.progress_controller.update(
            done=done,
            total=total,
            title=f"{friendly_phase} {done}/{total}",
            detail=f"{friendly_phase}：处理第 {done}/{total} 张，当前 {filename} | {self._elapsed_task_text()}",
            status=f"{friendly_phase} {done}/{total}，当前：{filename}",
            dialog_title="修复图片中",
            dialog_header="正在分析并修复图片",
        )

    def _update_repair_phase(self, done: int, total: int, filename: str, phase: str) -> None:
        now = time.monotonic()
        if now - self._last_repair_phase_update < 0.12:
            return
        self._last_repair_phase_update = now
        friendly_phase = self._friendly_repair_phase(phase)
        current_index = min(total, done + 1)
        self.progress_controller.update(
            done=done,
            total=total,
            title=f"修复中 {done}/{total}",
            detail=f"{friendly_phase}：处理第 {current_index}/{total} 张，当前 {filename} | {self._elapsed_task_text()}",
            status=f"{friendly_phase}，当前：{filename}",
            dialog_title="修复图片中",
            dialog_header="正在分析并修复图片",
        )

    def _friendly_analysis_phase(self, phase: str) -> str:
        if "读取" in phase or "图像" in phase:
            return "读取图片"
        if "亮度" in phase or "主体" in phase or "背景" in phase:
            return "分析曝光与画面结构"
        if "锐度" in phase or "色彩" in phase or "人像" in phase:
            return "分析色彩与清晰度"
        if "问题" in phase or "建议" in phase:
            return "生成问题与修复建议"
        if "指标" in phase or "最终" in phase:
            return "整理诊断结果"
        return phase

    def _friendly_repair_phase(self, phase: str) -> str:
        if "修复前分析" in phase:
            return "读取图片并补充分析"
        if "跳过失败项" in phase:
            return "整理不可处理图片"
        if "生成修复方案" in phase:
            return "生成修复方案"
        if "读取图片" in phase or "元数据" in phase:
            return "读取图片与元数据"
        if "曝光" in phase or "色彩" in phase or "清晰度" in phase:
            return "处理曝光、色彩与清晰度"
        if "人像" in phase:
            return "处理人像与画面细节"
        if "准备保存" in phase:
            return "准备保存结果"
        if "保存" in phase:
            return "保存结果"
        return "生成并保存修复结果" if "修复" in phase else phase

    def _update_analysis_phase(self, path: Path, step: int, steps: int, phase: str, total_images: int, run_id: int) -> None:
        if run_id != self._analysis_run_id or (self._analysis_cancel_event is not None and self._analysis_cancel_event.is_set()):
            return
        normalized_step = max(0, min(ANALYSIS_PROGRESS_STEPS, int(round(step * ANALYSIS_PROGRESS_STEPS / max(1, steps)))))
        previous = self.analysis_phase_progress.get(path, 0)
        if normalized_step > previous:
            self.analysis_phase_progress[path] = normalized_step
        aggregate_done = sum(self.analysis_phase_progress.values())
        finished_images = sum(1 for value in self.analysis_phase_progress.values() if value >= ANALYSIS_PROGRESS_STEPS)
        now = time.monotonic()
        force_update = normalized_step >= ANALYSIS_PROGRESS_STEPS or aggregate_done >= total_images * ANALYSIS_PROGRESS_STEPS
        if not force_update and now - self._last_progress_ui_update < 0.10:
            return
        self._last_progress_ui_update = now
        friendly_phase = self._friendly_analysis_phase(phase)
        detail = f"处理第 {finished_images + 1}/{total_images} 张：{path.name} | {friendly_phase} | {self._elapsed_task_text()}"
        if total_images > 1:
            detail = f"批量分析 {finished_images}/{total_images} | 第 {min(total_images, finished_images + 1)}/{total_images} 张：{path.name} | {friendly_phase} | {self._elapsed_task_text()}"
        self.progress_controller.update(
            done=aggregate_done,
            total=max(1, total_images * ANALYSIS_PROGRESS_STEPS),
            title=f"分析中 {finished_images}/{total_images}",
            detail=detail,
            status=detail,
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
        )

    def _update_similarity_detection_phase(self, total: int, run_id: int) -> None:
        if run_id != self._analysis_run_id or (self._analysis_cancel_event is not None and self._analysis_cancel_event.is_set()):
            return
        self.progress_controller.update(
            done=total * ANALYSIS_PROGRESS_STEPS,
            total=max(1, total * ANALYSIS_PROGRESS_STEPS),
            title="检测相似图片",
            detail=f"分析已完成，正在使用缩略图哈希和摘要特征检测本轮相似图片组。{self._elapsed_task_text()}",
            status="正在检测相似图片组",
            dialog_title="分析图片中",
            dialog_header="正在逐张分析图片",
        )

    def _analysis_finished(
        self,
        total: int,
        run_id: int,
        similar_groups: list[SimilarImageGroup] | None = None,
        batch_timings: dict[str, float] | None = None,
        worker_plan: AnalysisWorkerPlan | None = None,
        gpu_status: GPUBackendStatus | None = None,
    ) -> None:
        if run_id != self._analysis_run_id or (self._analysis_cancel_event is not None and self._analysis_cancel_event.is_set()):
            return
        batch_timings = dict(batch_timings or {})
        worker_plan = worker_plan or AnalysisWorkerPlan(
            mode=getattr(self.settings, "analysis_concurrency_mode", ANALYSIS_CONCURRENCY_AUTO),
            requested_workers=1,
            actual_workers=1,
        )
        gpu_status = gpu_status or resolve_gpu_status(getattr(self.settings, "gpu_acceleration_mode", GPU_ACCELERATION_OFF))
        target_paths = list(self._last_analysis_targets)
        issue_count = sum(1 for path in target_paths if path in self.results and self.results[path].issues)
        error_count = sum(1 for path in target_paths if path in self.errors)
        success_count = sum(1 for path in target_paths if path in self.results)
        similar_groups = similar_groups or []
        target_set = set(self._last_analysis_targets)
        self.similar_groups = [
            group for group in self.similar_groups if not any(path in target_set for path in group.paths)
        ]
        self.similar_groups.extend(similar_groups)
        similar_count = len(similar_groups)
        detail = f"分析完成：问题图片 {issue_count} 张，失败 {error_count} 张，相似组 {similar_count} 组。"
        self._log_console(f"analysis finished: count={total} issues={issue_count} errors={error_count} similar_groups={similar_count}")
        self._log_analysis_perf_rollup(
            self._last_analysis_targets,
            batch_timings,
            total=total,
            success=success_count,
            failed=error_count,
            canceled=0,
            worker_plan=worker_plan,
            gpu_status=gpu_status,
        )
        for group in similar_groups:
            self._log_console(
                f"similar group: #{group.group_id} count={len(group.paths)} score={group.similarity:.2f} | {group.reason}"
            )
        self.analysis_phase_progress = {}
        self.refresh_tree()
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
        self._analysis_cancel_event = None
        self._analysis_cancel_targets = []
        current = self._current_path()
        if current is not None:
            self.show_preview(current)
        self._maybe_prompt_cleanup_candidates(self._last_analysis_targets)
        self._maybe_prompt_similar_groups(similar_groups)
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

    def _maybe_prompt_similar_groups(self, groups: list[SimilarImageGroup]) -> None:
        groups = [group for group in groups if len([path for path in group.paths if path.exists()]) >= 2]
        if not groups:
            return
        self._log_console(f"similar detection summary: groups={len(groups)}")
        self.open_similar_group_window(groups)

    def open_similar_group_window(self, groups: list[SimilarImageGroup] | None = None) -> None:
        self._prune_missing_paths()
        active_groups = groups if groups is not None else self.similar_groups
        active_groups = [group for group in active_groups if len([path for path in group.paths if path.exists()]) >= 2]
        if not active_groups:
            messagebox.showinfo("提示", "当前没有可复核的相似图片组。")
            return
        cleanup_paths = set(self._primary_cleanup_candidates())
        show_similar_group_list_dialog(
            self.root,
            active_groups,
            self.results,
            cleanup_paths,
            self._open_similar_decision_window,
        )
        self._prune_similar_groups()
        self.refresh_tree()

    def _open_similar_decision_window(self, groups: list[SimilarImageGroup]) -> None:
        cleanup_paths = set(self._primary_cleanup_candidates())
        show_similar_group_decision_dialog(
            self.root,
            groups,
            self.results,
            cleanup_paths,
            self._delete_similar_image,
        )
        self._prune_similar_groups()
        self.refresh_tree()

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
        self._log_repair_perf_rollup(repaired + skipped)
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

        outcome_counts = {
            "normal_saved": 0,
            "forced_saved": 0,
            "forced_rollback": 0,
            "forced_skip_unsuitable": 0,
            "discard_candidate_skipped": 0,
        }
        for record in repaired + skipped:
            outcome_counts[record.outcome_category] = outcome_counts.get(record.outcome_category, 0) + 1

        lines = [
            f"已修复 {len(repaired)} 张",
            f"已跳过 {len(skipped)} 张",
            f"失败 {len(failed)} 张",
            f"强制尝试后保存 {outcome_counts['forced_saved']} 张",
            f"强制尝试但未保存 {outcome_counts['forced_rollback'] + outcome_counts['forced_skip_unsuitable']} 张",
        ]
        if selection.mode == "manual":
            labels = "、".join(get_method_labels(selection.selected_method_ids)) or "无"
            lines.append(f"统一方法：{labels}")
        else:
            lines.append("修复模式：按检测结果自动推荐")
        lines.append(
            "强制修复不值得保留图片："
            + ("已启用（仅允许尝试，仍会回退或跳过保存）" if selection.force_repair_cleanup_candidates else "未启用")
        )

        if selection.overwrite_original:
            lines.append("输出方式：覆盖原文件")
        else:
            lines.append(f"输出目录：{Path(self._resolve_base_folder()).resolve() / selection.output_folder_name}")
            lines.append(f"文件后缀：{selection.filename_suffix or '(无后缀)'}")
        if outcome_counts["normal_saved"]:
            lines.append(f"正常修复：{outcome_counts['normal_saved']} 张")
        if outcome_counts["forced_rollback"]:
            lines.append(f"强制尝试修复但回退：{outcome_counts['forced_rollback']} 张")
        if outcome_counts["forced_skip_unsuitable"] or outcome_counts["discard_candidate_skipped"]:
            lines.append(
                f"因仍不适合而跳过：{outcome_counts['forced_skip_unsuitable'] + outcome_counts['discard_candidate_skipped']} 张"
            )

        outcome_labels = {
            "normal_saved": "正常修复",
            "forced_saved": "强制尝试修复后保存",
            "forced_rollback": "强制尝试修复但回退",
            "forced_skip_unsuitable": "因仍不适合而跳过",
            "discard_candidate_skipped": "默认跳过不值得保留图片",
            "normal_skipped": "常规跳过",
        }
        show_repair_completion_dialog(
            self.root,
            title="修复完成",
            summary_lines=lines,
            entries=self._build_repair_completion_entries(repaired, skipped, failed, outcome_labels),
            default_filter=self.settings.repair_summary_default_filter or REPAIR_SUMMARY_FILTER_ALL,
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

    def _ops_text(self, record: RepairRecord) -> str:
        parts: list[str] = []
        if record.method_ids:
            parts.append("ops=" + ",".join(record.method_ids))
        if record.op_strengths:
            strength_text = ", ".join(f"{name}:{value:.2f}" for name, value in record.op_strengths.items())
            parts.append(f"strengths={strength_text}")
        return " | ".join(parts) if parts else "ops=none"

    def _repair_entry_filter_tags(self, record: RepairRecord, *, saved_output: bool) -> set[str]:
        tags = {REPAIR_SUMMARY_FILTER_REPAIRED if saved_output else REPAIR_SUMMARY_FILTER_SKIPPED}
        if record.forced_repair:
            if saved_output:
                tags.add(REPAIR_SUMMARY_FILTER_FORCED_SAVED)
            else:
                tags.add(REPAIR_SUMMARY_FILTER_FORCED_UNSAVED)
            tags.add(REPAIR_SUMMARY_FILTER_DISCARD_RELATED)
        if record.outcome_category == "discard_candidate_skipped":
            tags.add(REPAIR_SUMMARY_FILTER_DISCARD_RELATED)
        if record.outcome_category in {"forced_rollback", "normal_skipped"}:
            reason_text = (record.skipped_reason or "").lower()
            note_text = " ".join(record.policy_notes).lower()
            if "no-op" in reason_text or "回退" in record.skipped_reason or "no-op" in note_text or "回退" in note_text:
                tags.add(REPAIR_SUMMARY_FILTER_ROLLBACK_NOOP)
        if record.outcome_category == "forced_rollback":
            tags.add(REPAIR_SUMMARY_FILTER_ROLLBACK_NOOP)
        return tags

    def _build_repair_detail_lines(self, record: RepairRecord, *, include_output: bool) -> list[str]:
        lines = [self._ops_text(record)]
        if include_output:
            lines.append(f"输出文件：{record.output_path}")
        if record.skipped_reason:
            lines.append(f"skip reason：{record.skipped_reason}")
        if record.applied_strength is not None:
            lines.append(f"applied strength：{record.applied_strength:.2f}")
        denoise_strength = record.op_strengths.get("reduce_noise")
        if denoise_strength is not None:
            lines.append(f"denoise：{denoise_strength:.2f}")
        for note in record.policy_notes:
            lines.append(f"note：{note}")
        for warning in record.warnings:
            lines.append(f"warning：{warning}")
        for note in record.perf_notes:
            lines.append(f"perf：{note}")
        return lines

    def _build_repair_completion_entries(
        self,
        repaired: list[RepairRecord],
        skipped: list[RepairRecord],
        failed: list[tuple[Path, str]],
        outcome_labels: dict[str, str],
    ) -> list[RepairCompletionEntry]:
        entries: list[RepairCompletionEntry] = []
        for record in repaired:
            status = outcome_labels.get(record.outcome_category, record.outcome_category)
            primary_reason = "已生成修复输出。"
            if record.forced_repair:
                primary_reason = "强制尝试后通过评分与安全检查，已保存修复结果。"
            entries.append(
                RepairCompletionEntry(
                    file_name=record.source_path.name,
                    status=status,
                    primary_reason=primary_reason,
                    ops_or_skip=self._ops_text(record),
                    forced=record.forced_repair,
                    filter_tags=self._repair_entry_filter_tags(record, saved_output=True),
                    detail_lines=self._build_repair_detail_lines(record, include_output=True),
                )
            )
        for record in skipped:
            status = outcome_labels.get(record.outcome_category, record.outcome_category)
            reason = record.skipped_reason or "当前方案未生成修复输出。"
            entries.append(
                RepairCompletionEntry(
                    file_name=record.source_path.name,
                    status=status,
                    primary_reason=reason,
                    ops_or_skip=reason if not record.method_ids else f"{reason} | {self._ops_text(record)}",
                    forced=record.forced_repair,
                    filter_tags=self._repair_entry_filter_tags(record, saved_output=False),
                    detail_lines=self._build_repair_detail_lines(record, include_output=False),
                )
            )
        for path, message in failed:
            entries.append(
                RepairCompletionEntry(
                    file_name=path.name,
                    status="失败",
                    primary_reason=message,
                    ops_or_skip=message,
                    forced=False,
                    filter_tags={REPAIR_SUMMARY_FILTER_FAILED},
                    detail_lines=[f"文件：{path}", f"错误：{message}"],
                )
            )
        return entries

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

    def _similar_marker_for_path(self, path: Path) -> str:
        group_ids = [str(group.group_id) for group in self.similar_groups if path in group.paths and len(group.paths) >= 2]
        if not group_ids:
            return ""
        return f"相似组#{'/'.join(group_ids[:2])}"

    def _tree_row_values(self, path: Path) -> tuple[str, str, str, str]:
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
        similar_marker = self._similar_marker_for_path(path)
        if similar_marker:
            tags = f"{tags} | {similar_marker}" if tags else similar_marker
        return checked, status, risk, tags

    def _refresh_tree_item(self, path: Path) -> bool:
        item_id = self.path_item_lookup.get(path)
        if not item_id or not self.tree.exists(item_id):
            return False
        if not self._matches_filter(self.results.get(path), self.errors.get(path)):
            self.tree.delete(item_id)
            self.item_lookup.pop(item_id, None)
            self.path_item_lookup.pop(path, None)
            return True
        self.tree.item(item_id, text=path.name, values=self._tree_row_values(path))
        return True

    def refresh_tree(self) -> None:
        self._prune_missing_paths()
        current_path = self._current_path()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.item_lookup.clear()
        self.path_item_lookup.clear()

        for path in self._sorted_paths():
            thumb = self.thumb_cache.get_tree_thumbnail(path)
            item_id = self.tree.insert("", "end", text=path.name, image=thumb, values=self._tree_row_values(path))
            self.item_lookup[item_id] = path
            self.path_item_lookup[path] = item_id
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
        self._prune_similar_groups()
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
            lines.append(
                f"noise：{result.noise_level} ({result.noise_score:.4f}) | "
                f"denoise_profile={result.denoise_profile} | recommended={'是' if result.denoise_recommended else '否'}"
            )
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
            similar_marker = self._similar_marker_for_path(path)
            if similar_marker:
                lines.append("")
                lines.append(f"相似图片标记：{similar_marker}。可在“查看 -> 打开相似图片组”中复核。")
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
        similar_hint = " | 相似组" if self._similar_marker_for_path(path) else ""
        if result.issues:
            tags = "、".join(issue.label for issue in result.issues[:4])
            methods = "、".join(get_method_labels(suggest_methods_for_result(result))) or "暂无明确推荐"
            face_info = f" | raw/valid/reject {result.raw_face_count}/{result.validated_face_count}/{result.rejected_face_count}" if (result.raw_face_count or result.validated_face_count or result.rejected_face_count) else ""
            cleanup_hint = " | 建议删除候选" if result.cleanup_candidates else ""
            self.hud_tags_var.set(f"识别结果：{tags}{face_info}{cleanup_hint}{similar_hint}")
            if result.denoise_recommended:
                methods = f"{methods} | 降噪:{result.denoise_profile}"
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
            cleanup_hint = " | 建议删除候选" if result.cleanup_candidates else ""
            self.hud_tags_var.set(f"识别结果：未发现明显问题{portrait_hint}{cleanup_hint}{similar_hint}")
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

    def _delete_similar_image(self, path: Path, group: SimilarImageGroup) -> bool:
        if not path.exists():
            group.paths[:] = [item for item in group.paths if item != path]
            self._remove_path_from_list(path, refresh=False)
            self.refresh_tree()
            return True
        result = self.results.get(path)
        cleanup_marker = "；该图同时是不适合保留候选" if result and result.cleanup_candidates else ""
        confirm = messagebox.askyesno(
            "确认删除相似图片",
            "将优先尝试移入系统回收站；若系统不支持，则移入项目内安全隔离目录 `_cleanup_candidates`。\n\n"
            f"相似组 {group.group_id}：{path.name}{cleanup_marker}\n\n是否继续？",
        )
        if not confirm:
            return False
        try:
            operation = safe_cleanup_paths([path], self._resolve_base_folder())
        except Exception as exc:
            self._log_console(f"similar delete failed: {path.name} | {exc}")
            messagebox.showerror("无法删除", f"未能安全删除 {path.name}：\n{exc}")
            return False
        if operation.moved < 1 and path.exists():
            messagebox.showerror("无法删除", f"未能安全删除 {path.name}：\n{operation.destination_label}")
            return False

        self._remove_path_from_list(path, refresh=False)
        self.image_paths = [item for item in self.image_paths if item.exists()]
        group.paths[:] = [item for item in group.paths if item != path and item.exists()]
        self._prune_similar_groups()
        self.refresh_tree()
        current = self._current_path()
        if current is None and self.image_paths:
            self._select_path(self.image_paths[0])
        detail = f"已安全清理相似图片：{path.name} -> {operation.destination_label}"
        self._log_console(f"similar image handled: group={group.group_id} mode={operation.mode} moved={operation.moved} destination={operation.destination_label}")
        self.status_var.set(detail)
        return True

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

        try:
            operation = safe_cleanup_paths(chosen, self._resolve_base_folder())
        except Exception as exc:
            self._log_console(f"cleanup candidates failed: {exc}")
            messagebox.showerror("无法删除", f"安全清理失败：\n{exc}")
            return
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

        try:
            operation = safe_cleanup_paths(chosen, self._resolve_base_folder())
        except Exception as exc:
            self._log_console(f"cleanup failed: {exc}")
            messagebox.showerror("无法删除", f"安全清理失败：\n{exc}")
            return
        for path in chosen:
            self._remove_path_from_list(path, refresh=False)

        self.image_paths = [path for path in self.image_paths if path.exists()]
        self.refresh_tree()
        self._log_console(f"cleanup moved: mode={operation.mode} moved={operation.moved} -> {operation.destination_label}")
        self.status_var.set(f"已安全清理 {operation.moved} 张图片：{operation.destination_label}")
        messagebox.showinfo("完成", f"已安全清理 {operation.moved} 张图片：\n{operation.destination_label}")
