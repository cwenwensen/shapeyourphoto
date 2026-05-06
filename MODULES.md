# 模块维护说明

这份文档面向后续继续接手本项目的人，目标是让新接手者在尽量少翻代码的前提下，快速理解结构、数据流、修改入口和当前边界。

说明：
- `docs/` 下的正式维护文档是当前权威来源。
- 本文件保留为快速索引与兼容说明；如果与 `docs/` 或 `docs/updates/1.1.4.md` 冲突，以后者为准。

## 总体结构

- [app.py](/E:/aitools/shapeyourphoto/app.py)
  主入口。负责创建主窗口并启动 GUI。

- [app.pyw](/E:/aitools/shapeyourphoto/app.pyw)
  无控制台 Python GUI 启动入口。

- [ui_app.py](/E:/aitools/shapeyourphoto/ui_app.py)
  主界面控制中心。负责目录读取、列表管理、预览、分析触发、修复触发、统计入口、Console 刷新和右侧四区显示。

## 分析链路

- [analyzer.py](/E:/aitools/shapeyourphoto/analyzer.py)
  图像分析核心。输入图片路径，输出 `AnalysisResult`。这里负责：
  - 亮度、对比度、锐度、饱和度、噪声等基础特征计算
  - 问题标签生成
  - 关键指标填充
  - 阶段性进度回调

- [models.py](/E:/aitools/shapeyourphoto/models.py)
  所有分析结果、修复配置、统计数据的统一数据结构定义。新增字段时优先先改这里，再接到其他模块。

## 修复链路

- [repair_planner.py](/E:/aitools/shapeyourphoto/repair_planner.py)
  负责把问题标签映射到修复方法推荐，并根据 `denoise_profile`、cleanup candidate 等上下文做单图限幅。

- [repair_ops.py](/E:/aitools/shapeyourphoto/repair_ops.py)
  具体修复算子层。每个函数尽量只做一种修复动作。当前大部分方法支持根据 `AnalysisResult` 自适应计算强度；`reduce_noise` 已升级为场景化降噪。

- [repair_engine.py](/E:/aitools/shapeyourphoto/repair_engine.py)
  修复执行层。负责：
  - 选择修复方法
  - 执行方法链
  - 生成输出路径
  - 写回 EXIF / DPI / ICC / XMP
  - 写入修改来源信息
  - cleanup candidate 强制尝试修复、结果分类与附加回退判断

- [repair_dialog.py](/E:/aitools/shapeyourphoto/repair_dialog.py)
  修复对话框。负责模式选择、方法勾选、输出目录、后缀、覆盖原文件，以及“强制修复不值得保留的图片”开关。

## 文件与列表

- [file_actions.py](/E:/aitools/shapeyourphoto/file_actions.py)
  目录扫描、带进度扫描、忽略目录前缀、导出清理清单、移动到清理目录、生成修复输出路径。

- [app_settings.py](/E:/aitools/shapeyourphoto/app_settings.py)
  扫描忽略目录前缀的持久化设置。

- [scan_dialogs.py](/E:/aitools/shapeyourphoto/scan_dialogs.py)
  目录扫描四选项与忽略前缀设置对话框。

- [preview_cache.py](/E:/aitools/shapeyourphoto/preview_cache.py)
  左侧缩略图缓存。

- [result_sorting.py](/E:/aitools/shapeyourphoto/result_sorting.py)
  左侧列表排序逻辑，避免排序规则直接散落在 UI 代码里。

## 进度与状态

- [progress_dialog.py](/E:/aitools/shapeyourphoto/progress_dialog.py)
  统一进度控制器。目录扫描、分析、修复都应走这里，不要再直接在业务线程里零散改控件。

- [app_console.py](/E:/aitools/shapeyourphoto/app_console.py)
  只读日志缓存。用于 GUI 内部 Console 面板，显示扫描、分析、修复和清理过程，不提供命令输入能力。

## 桌面与窗口

- [desktop_integration.py](/E:/aitools/shapeyourphoto/desktop_integration.py)
  程序图标和任务栏集成。

- [window_layout.py](/E:/aitools/shapeyourphoto/window_layout.py)
  Windows 工作区居中布局，避免窗口压到顶部任务栏或透明任务栏区域。所有二级窗口优先也走这里。

- [drag_drop.py](/E:/aitools/shapeyourphoto/drag_drop.py)
  原生 Windows 文件拖入支持。当前使用 `WM_DROPFILES` 方式，不依赖第三方拖拽库。

## 1.1.4 补充维护说明

- 独立“单图模式”已移除；当前保留的是“选择单张图片加入主列表”能力，而不是独立窗口模式。
- 扫描入口现在都必须遵守 `_repair*` 前缀跳过规则，并把扫描模式、跳过目录数量和导入图片数量写入摘要。
- 去噪已经并入统一分析与修复链，后续不要再恢复孤立的“去噪当前”旧入口。

## 属性、签名与附属模块

- [metadata_utils.py](/E:/aitools/shapeyourphoto/metadata_utils.py)
  右侧属性 / EXIF 面板的摘要生成。

- [watermark_signature.py](/E:/aitools/shapeyourphoto/watermark_signature.py)
  可见水印/电子签名叠加模块。当前保留但默认不接入修复流程。后续如果重新启用，应在文档里同步说明输出会出现可见标注。

## 统计与报表

- [stats_store.py](/E:/aitools/shapeyourphoto/stats_store.py)
  累计统计的持久化入口，默认落地到工作区 `usage_stats.json`。重新打开程序后会继续累积。

- [stats_dialog.py](/E:/aitools/shapeyourphoto/stats_dialog.py)
  统计窗口、摘要显示和检出率曲线绘制。

## 文档与版本

- [app_metadata.py](/E:/aitools/shapeyourphoto/app_metadata.py)
  程序名、版本号、更新历史数据源。

- [history_dialog.py](/E:/aitools/shapeyourphoto/history_dialog.py)
  更新历史弹窗。

- [README.md](/E:/aitools/shapeyourphoto/README.md)
  使用说明、能力边界、元数据/HDR/水印说明。

- [CHANGELOG.md](/E:/aitools/shapeyourphoto/CHANGELOG.md)
  版本变更记录。

## 当前数据流

1. 用户通过选择目录、选择图片或拖入内容，把路径加入 `ui_app.py` 的列表状态。
2. `scan_image_paths_with_progress()` 在扫描目录时回调进度给 `TaskProgressController`。
3. `analyze_image()` 负责单张图片分析，并把阶段进度回传给主界面。
4. `AnalysisResult` 被缓存到 `self.results`，同时更新左侧列表、右侧条图、右侧说明和 HUD。
5. 用户发起修复后，`repair_planner.py` 负责推荐方法，`repair_engine.py` 执行修复并输出文件。
6. 分析和修复动作都会更新 `stats_store.py` 中的累计统计。

## 修改建议

- 新增一种检测问题：
  先改 [analyzer.py](/E:/aitools/shapeyourphoto/analyzer.py)，再视需要补 [repair_planner.py](/E:/aitools/shapeyourphoto/repair_planner.py)。

- 新增一种修复方法：
  先在 [repair_ops.py](/E:/aitools/shapeyourphoto/repair_ops.py) 写算子，再接到 [repair_engine.py](/E:/aitools/shapeyourphoto/repair_engine.py)。

- 改布局或交互：
  优先改 [ui_app.py](/E:/aitools/shapeyourphoto/ui_app.py)，不要把业务判断拆散到多个 UI 文件。

- 改进度体验：
  优先改 [progress_dialog.py](/E:/aitools/shapeyourphoto/progress_dialog.py)，保持统一入口。

- 改拖入能力：
  优先检查 [drag_drop.py](/E:/aitools/shapeyourphoto/drag_drop.py) 和 [ui_app.py](/E:/aitools/shapeyourphoto/ui_app.py) 的 `_handle_dropped_paths()`。

- 改元数据写回：
  优先改 [repair_engine.py](/E:/aitools/shapeyourphoto/repair_engine.py)。

## 当前边界与已知说明

- `Digital Signatures` 不是普通图片 EXIF/XMP 字段，当前程序不会生成 Windows 文件属性中的真正代码签名页。
- HDR 相关扩展信息只能保留到底层 Pillow 能完整读写的范围；专有增益图或厂商私有结构不能保证完全无损回写。
- 可见水印默认关闭；如需启用，应通过 [watermark_signature.py](/E:/aitools/shapeyourphoto/watermark_signature.py) 单独接入。
## 1.1.4 Addendum
- 1.1.4 体验与配置完善补充：
  - 新增 [settings_dialog.py](/E:/aitools/shapeyourphoto/settings_dialog.py)，作为统一应用设置面板。
  - 新增 [scan_summary_dialog.py](/E:/aitools/shapeyourphoto/scan_summary_dialog.py)，用于查看按前缀聚合后的跳过目录明细。
  - [repair_completion_dialog.py](/E:/aitools/shapeyourphoto/repair_completion_dialog.py) 已从纯文本详情升级为带筛选的滚动结果视图。
  - [app_settings.py](/E:/aitools/shapeyourphoto/app_settings.py) 现已负责默认值、校验、自动创建和损坏回退，不再只是单一前缀存储器。

- 以 `docs/` 为准的正式维护文档已经补充 1.1.4 说明；如果本文件和 `docs/` 有冲突，以 `docs/` 为准。
- `analyzer.py` 现已成为兼容入口，分析主逻辑迁移到 `analysis/` 包。
- 1.1.4 的核心维护主题是场景感知分析、单图自适应 repair plan、通用 cleanup candidate 机制，以及批量并发与主线程 UI 安全。
