# Maintenance Guide

本文是 1.1.6 当前维护规则。旧版本附录保留在 `docs/updates/`；如旧说明与本文冲突，以本文和当前代码为准。

## 基本原则

1. 先核代码，再改文档或实现。
2. 小步修改、可验证，不借维护任务重构核心算法。
3. 保留用户数据安全边界：不上传图片、不永久删除、不暗改输出规则。
4. 功能变化必须同步文档、CHANGELOG 和 `app_metadata.py`。
5. 不提交本地样张、缓存、patch、`__pycache__`、调试输出或临时文件。

## 启动链路保护

- 日常启动入口是 `start.bat` / `start_app.bat` / `app.pyw` / `app.py`。
- 启动脚本必须短、快、稳。
- 不得把 `pip install`、benchmark、扫描、清理或耗时检查放入日常启动。
- 依赖安装只走 `setup_deps.bat` 或明确的人工命令。

## Tk 主线程规则

- Tk 控件只能在主线程更新。
- 后台线程不得直接写 Treeview、Text、Label、Progressbar 或弹窗。
- 目录扫描、批量分析、批量修复和相似检测应通过回调/队列/`root.after()` 回主线程。
- Console Text 刷新必须保持合并刷新，避免每条日志重绘整块内容。
- 分析/修复进度窗口只显示固定高度阶段摘要；长阶段详情和性能细节进入 Console，不得撑开弹窗内部布局。
- 进度窗口只允许一个明确取消入口，关闭叉号与按钮应走同一取消路径。

## UI 主类拆分规则

- `ui_app.py` 只负责主窗口状态、控件装配和高层协调。
- 扫描/导入、分析任务、修复任务、主列表、Console/perf、cleanup/similar 复核分别维护在 `ui_scan_actions.py`、`ui_analysis_actions.py`、`ui_repair_actions.py`、`ui_file_list.py`、`ui_task_console.py`、`ui_review_actions.py`。
- 新增 UI 行为时优先放入对应 mixin；只有布局装配、菜单 wiring 和根窗口生命周期适合留在 `ui_app.py`。
- mixin 模块不得 import `ui_app.py`，共享常量放在 `ui_constants.py`，避免循环依赖。
- 拆分 UI 代码时必须保持后台回调回主线程、run_id/cancel_event 防旧写回和 Console 合并刷新规则。

## 后台线程、run_id 与取消规则

- 每轮批量分析都应有唯一 run_id。
- 取消分析通过 cancel_event 表达。
- 后台任务写回结果、进度、cleanup prompt、similar prompt 或最终摘要前必须校验 run_id 和 cancel_event。
- 取消后保留文件列表，清空本轮目标已写入的结果、错误、进度、cleanup 标记和相似组标记。
- 已取消 worker 可以完成 CPU 工作，但结果必须丢弃。

## perf_timings / perf_notes 规则

- 分析和修复耗时统一写入 `perf_timings`。
- 面向维护者的轻量瓶颈提示写入 `perf_notes`。
- 不要新建平行计时体系。
- 分析建议记录读取、EXIF 转正、working image、基础统计、曝光、锐度、色彩、噪声、人像、cleanup candidate、相似图检测等阶段。
- 修复建议记录 planner、读取、各 op、候选生成/评分、安全检查、保存输出和元数据保留。
- Console 以 wall time 为主；worker cumulative 是并发 worker 累计工作量，不是用户等待时间。

## EXIF Orientation 归一

- 读取图片时使用 `ImageOps.exif_transpose` 将像素方向转正。
- 保存 JPEG/WebP 前将 EXIF Orientation 归一为 `1`。
- 回归时检查原图显示方向、输出物理尺寸和输出 Orientation。

## cleanup candidate 安全删除规则

- cleanup candidate 是建议，不是自动删除命令。
- UI 默认不勾选候选。
- 删除前必须二次确认。
- 删除必须走 `safe_cleanup_paths()`。
- 优先移入系统回收站；失败时移入项目内 `_cleanup_candidates` 隔离目录。
- 不得在 cleanup 或 similar 窗口中直接 `unlink()` 或永久删除。

## 修复目标集合规则

- “修复当前”只读取当前焦点图片。
- “批量修复勾选”优先使用真正的 Treeview 多选集合；只有当多选数量多于 1 张时才视为批量多选。
- 没有真正多选时，批量入口回退到勾选集合；单个蓝色高亮行不得覆盖勾选集合。
- 批量修复必须逐图调用 `repair_engine.repair_image_file()`，并让 `repair_planner.build_repair_plan()` 基于该图自己的 `AnalysisResult` 生成 `method_ids`、`op_strengths` 和 policy notes。
- 不得把当前焦点图的推荐方法、参数或力度套用到整批图片。
- 修复完成详情的成功、跳过、失败、候选回退/no-op 统计必须来自真实批量目标结果。

## 弹窗尺寸规则

- 分析/修复进度、扫描四选项、修复完成详情、cleanup candidate、相似图列表、相似图组内对比和设置窗口都应有明确 `minsize()` 或固定/滚动策略。
- 底部关键按钮应放在固定按钮区，内容过长时滚动内容区，不压缩按钮区。
- 可缩放窗口达到最小尺寸附近时，统一显示“已达到最小可用窗口大小”。
- 二级窗口默认尺寸必须受屏幕可用区域限制，不能为了展示完整内容超出屏幕。

## 相似图维护规则

- 相似图只作为分析批次附加结果。
- `SimilarImageGroup` 不写回单张 `AnalysisResult.issues`、`scene_type`、人像字段、修复建议或 cleanup candidates。
- 同一张图可以同时出现在 cleanup candidate 和 similar group 中；UI 只能提示，不自动处理。
- 相似图删除复用全局安全清理。

## 设置与扫描规则

- 应用设置统一由 `app_settings.py` 定义、校验和保存。
- UI 设置统一由 `settings_dialog.py` 管理，不新增零散菜单项。
- 扫描默认至少忽略 `_repair` 前缀，任意层级以 `_repair` 开头的目录都跳过。
- 扫描结果应写入 Console 简报和“最近扫描摘要”明细。
- 修改扫描逻辑时同时验证按钮扫描、拖拽文件夹、补扫、默认扫描模式和忽略前缀。

## GPU fallback 规则

- GPU 是可选检测，不是硬依赖。
- 不得把 CuPy、OpenCV-CUDA、torch CUDA、CUDA runtime 等加入必需依赖。
- 未检测到 GPU 或可选依赖时，应用必须正常启动并回退 CPU。
- 未证明真实 offload 收益前，不要声称 GPU 已参与默认分析。

## `/test` 本地样张规则

- `test/` 用于本地真实图片 benchmark 和回归。
- 图片文件由 `.gitignore` 忽略，不得提交。
- 真实 `test/manifest.json` 也默认忽略，因为可能包含用户图片文件名。
- 可提交的模板是 `test/manifest.example.json`。
- `benchmark_test_images.py` 必须允许 `test/` 为空时安全跳过。
- benchmark 摘要应记录 wall time、worker cumulative、queue/wait、慢图、慢阶段、相似检测、问题图和 cleanup candidate 数量。
- benchmark 报告写入被忽略的 `benchmark_reports/`，不得提交报告文件。

## 文档更新规则

- 不得删除 `docs/`、`docs/technical/`、`docs/updates/`。
- 不得清空正式文档。
- 过时内容应修订、迁移、标注历史上下文或指向当前说明。
- 新增模块或职责变化：更新 `MODULE_REFERENCE.md`。
- UI 流程变化：更新 `UI_AND_WORKFLOWS.md`。
- 技术链路变化：更新或新增 `docs/technical/` 专题。
- 版本升级：更新 `CHANGELOG.md`、`app_metadata.py` 和 `docs/updates/<version>.md`。

## 推荐验证顺序

1. `python -m compileall -q .`
2. 静态检查 `start.bat` / `start_app.bat` 未加入依赖安装或耗时逻辑。
3. 搜索旧入口描述：`single_image_window`、孤立“去噪当前”、普通 `messagebox` 长修复详情。
4. 检查文档是否存在明显乱码。
5. 检查 `git status --short`，确认没有本地样张、`__pycache__`、patch、tmp 或 debug 输出进入版本控制。

## 高风险修改点

- `ui_app.py` 与 `ui_*` mixin：主线程、run_id、取消、列表刷新、Console 合并刷新和弹窗入口。
- `analysis/core.py` / `analysis/portrait.py`：分析结论与人像误判。
- `repair_ops.py` / `repair_engine.py`：视觉风格、输出安全和元数据。
- `file_actions.py`：扫描忽略、清理安全和输出路径。
- `app_settings.py`：设置兼容、默认值和 worker 规划。
- `similar_detector.py` / `similar_review_dialog.py`：相似图算法与安全删除。
