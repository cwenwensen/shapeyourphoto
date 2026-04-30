# 模块维护说明

这份文档面向后续继续接手本项目的人，目标是让新接手者在尽量少翻代码的前提下，快速理解结构、数据流、修改入口和当前边界。

## 总体结构

- [app.py](/E:/aitools/codexAuto_photosAnalyzer/app.py)
  主入口。负责创建主窗口并启动 GUI。

- [app.pyw](/E:/aitools/codexAuto_photosAnalyzer/app.pyw)
  无控制台 Python GUI 启动入口。

- [ui_app.py](/E:/aitools/codexAuto_photosAnalyzer/ui_app.py)
  主界面控制中心。负责目录读取、列表管理、预览、分析触发、修复触发、统计入口、Console 刷新和右侧四区显示。

- [single_image_window.py](/E:/aitools/codexAuto_photosAnalyzer/single_image_window.py)
  单图大窗口模式入口。内部仍然复用 `PhotoAnalyzerApp`。

## 分析链路

- [analyzer.py](/E:/aitools/codexAuto_photosAnalyzer/analyzer.py)
  图像分析核心。输入图片路径，输出 `AnalysisResult`。这里负责：
  - 亮度、对比度、锐度、饱和度、噪声等基础特征计算
  - 问题标签生成
  - 关键指标填充
  - 阶段性进度回调

- [models.py](/E:/aitools/codexAuto_photosAnalyzer/models.py)
  所有分析结果、修复配置、统计数据的统一数据结构定义。新增字段时优先先改这里，再接到其他模块。

## 修复链路

- [repair_planner.py](/E:/aitools/codexAuto_photosAnalyzer/repair_planner.py)
  负责把问题标签映射到修复方法推荐。

- [repair_ops.py](/E:/aitools/codexAuto_photosAnalyzer/repair_ops.py)
  具体修复算子层。每个函数尽量只做一种修复动作。当前大部分方法支持根据 `AnalysisResult` 自适应计算强度。

- [repair_engine.py](/E:/aitools/codexAuto_photosAnalyzer/repair_engine.py)
  修复执行层。负责：
  - 选择修复方法
  - 执行方法链
  - 生成输出路径
  - 写回 EXIF / DPI / ICC / XMP
  - 写入修改来源信息

- [repair_dialog.py](/E:/aitools/codexAuto_photosAnalyzer/repair_dialog.py)
  修复对话框。负责模式选择、方法勾选、输出目录、后缀和覆盖原文件选项。

## 文件与列表

- [file_actions.py](/E:/aitools/codexAuto_photosAnalyzer/file_actions.py)
  目录扫描、带进度扫描、导出清理清单、移动到清理目录、生成修复输出路径。

- [preview_cache.py](/E:/aitools/codexAuto_photosAnalyzer/preview_cache.py)
  左侧缩略图缓存。

- [result_sorting.py](/E:/aitools/codexAuto_photosAnalyzer/result_sorting.py)
  左侧列表排序逻辑，避免排序规则直接散落在 UI 代码里。

## 进度与状态

- [progress_dialog.py](/E:/aitools/codexAuto_photosAnalyzer/progress_dialog.py)
  统一进度控制器。目录扫描、分析、修复都应走这里，不要再直接在业务线程里零散改控件。

- [app_console.py](/E:/aitools/codexAuto_photosAnalyzer/app_console.py)
  只读日志缓存。用于 GUI 内部 Console 面板，显示扫描、分析、修复和清理过程，不提供命令输入能力。

## 桌面与窗口

- [desktop_integration.py](/E:/aitools/codexAuto_photosAnalyzer/desktop_integration.py)
  程序图标和任务栏集成。

- [window_layout.py](/E:/aitools/codexAuto_photosAnalyzer/window_layout.py)
  Windows 工作区居中布局，避免窗口压到顶部任务栏或透明任务栏区域。所有二级窗口优先也走这里。

- [drag_drop.py](/E:/aitools/codexAuto_photosAnalyzer/drag_drop.py)
  原生 Windows 文件拖入支持。当前使用 `WM_DROPFILES` 方式，不依赖第三方拖拽库。

## 属性、签名与附属模块

- [metadata_utils.py](/E:/aitools/codexAuto_photosAnalyzer/metadata_utils.py)
  右侧属性 / EXIF 面板的摘要生成。

- [watermark_signature.py](/E:/aitools/codexAuto_photosAnalyzer/watermark_signature.py)
  可见水印/电子签名叠加模块。当前保留但默认不接入修复流程。后续如果重新启用，应在文档里同步说明输出会出现可见标注。

## 统计与报表

- [stats_store.py](/E:/aitools/codexAuto_photosAnalyzer/stats_store.py)
  累计统计的持久化入口，默认落地到工作区 `usage_stats.json`。重新打开程序后会继续累积。

- [stats_dialog.py](/E:/aitools/codexAuto_photosAnalyzer/stats_dialog.py)
  统计窗口、摘要显示和检出率曲线绘制。

## 文档与版本

- [app_metadata.py](/E:/aitools/codexAuto_photosAnalyzer/app_metadata.py)
  程序名、版本号、更新历史数据源。

- [history_dialog.py](/E:/aitools/codexAuto_photosAnalyzer/history_dialog.py)
  更新历史弹窗。

- [README.md](/E:/aitools/codexAuto_photosAnalyzer/README.md)
  使用说明、能力边界、元数据/HDR/水印说明。

- [CHANGELOG.md](/E:/aitools/codexAuto_photosAnalyzer/CHANGELOG.md)
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
  先改 [analyzer.py](/E:/aitools/codexAuto_photosAnalyzer/analyzer.py)，再视需要补 [repair_planner.py](/E:/aitools/codexAuto_photosAnalyzer/repair_ops.py)。

- 新增一种修复方法：
  先在 [repair_ops.py](/E:/aitools/codexAuto_photosAnalyzer/repair_ops.py) 写算子，再接到 [repair_engine.py](/E:/aitools/codexAuto_photosAnalyzer/repair_planner.py)。

- 改布局或交互：
  优先改 [ui_app.py](/E:/aitools/codexAuto_photosAnalyzer/ui_app.py)，不要把业务判断拆散到多个 UI 文件。

- 改进度体验：
  优先改 [progress_dialog.py](/E:/aitools/codexAuto_photosAnalyzer/progress_dialog.py)，保持统一入口。

- 改拖入能力：
  优先检查 [drag_drop.py](/E:/aitools/codexAuto_photosAnalyzer/drag_drop.py) 和 [ui_app.py](/E:/aitools/codexAuto_photosAnalyzer/ui_app.py) 的 `_handle_dropped_paths()`。

- 改元数据写回：
  优先改 [repair_engine.py](/E:/aitools/codexAuto_photosAnalyzer/repair_engine.py)。

## 当前边界与已知说明

- `Digital Signatures` 不是普通图片 EXIF/XMP 字段，当前程序不会生成 Windows 文件属性中的真正代码签名页。
- HDR 相关扩展信息只能保留到底层 Pillow 能完整读写的范围；专有增益图或厂商私有结构不能保证完全无损回写。
- 可见水印默认关闭；如需启用，应通过 [watermark_signature.py](/E:/aitools/codexAuto_photosAnalyzer/watermark_signature.py) 单独接入。
