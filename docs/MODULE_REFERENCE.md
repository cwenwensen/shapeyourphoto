# Module Reference

## 启动入口

### [start.bat](/E:/aitools/shapeyourphoto/start.bat)

- 推荐的日常双击入口
- 应只负责快速启动

### [start_app.bat](/E:/aitools/shapeyourphoto/start_app.bat)

- 兼容保留入口
- 不应在此加入日常依赖安装逻辑

### [setup_deps.bat](/E:/aitools/shapeyourphoto/setup_deps.bat)

- 首次安装依赖时使用
- 与日常启动隔离

### [app.py](/E:/aitools/shapeyourphoto/app.py) / [app.pyw](/E:/aitools/shapeyourphoto/app.pyw)

- Python 启动入口
- 创建主窗口并启动 GUI

## UI 与交互

### [ui_app.py](/E:/aitools/shapeyourphoto/ui_app.py)

- 主界面控制中心
- 管理列表、筛选、预览信息、分析、修复、进度、拖拽接入
- 这是最敏感的主流程文件之一
- `1.1.5` 起还负责 Console 合并刷新、分析/修复阶段耗时摘要、批量 top slow steps、分析 worker 并发设置消费、GPU 状态提示和主列表单行更新。

### [history_dialog.py](/E:/aitools/shapeyourphoto/history_dialog.py)

- 版本历史窗口

### [stats_dialog.py](/E:/aitools/shapeyourphoto/stats_dialog.py)

- 统计信息窗口

### [repair_dialog.py](/E:/aitools/shapeyourphoto/repair_dialog.py)

- 修复方案选择弹窗
- 包含“强制修复不值得保留的图片”开关
- 底部操作按钮可见性很重要

### [scan_dialogs.py](/E:/aitools/shapeyourphoto/scan_dialogs.py)

- 目录扫描四选项对话框
- 扫描忽略前缀设置对话框

### [debug_open_dialog.py](/E:/aitools/shapeyourphoto/debug_open_dialog.py)

- 修复完成后的调试打开弹窗
- 只负责选择并打开本轮成功修复的原图与输出图
- 不参与修复算法与输出逻辑

### [diagnostics_chart.py](/E:/aitools/shapeyourphoto/diagnostics_chart.py)

- 右侧指标条图区域
- 主要展示分析指标和问题强度

## 分析与修复

### [analyzer.py](/E:/aitools/shapeyourphoto/analyzer.py)

- 单张图片分析核心
- 负责亮度、对比、锐度、色彩、噪声、饱和度等判断
- 新增轻量人像感知分析，用于区分人像主体、背景与高亮区域
- 输出 `AnalysisResult`

### [repair_planner.py](/E:/aitools/shapeyourphoto/repair_planner.py)

- 把问题标签映射到修复方法
- 现已为暗背景和高调背景人像增加局部修复策略与背景保护策略
- 去噪推荐会结合 `noise_level` 与 `denoise_profile`

### [repair_ops.py](/E:/aitools/shapeyourphoto/repair_ops.py)

- 各类具体修复算子
- 修改这里时要重点关注视觉副作用
- `lift_shadows` 现包含人像主体与暗背景保护逻辑
- 新增基于粗 mask 的人像局部增强与高调背景保护能力
- `reduce_noise` 现为场景化降噪，需同时验证脸部纹理、建筑边缘与平滑背景

### [repair_engine.py](/E:/aitools/shapeyourphoto/repair_engine.py)

- 执行修复链
- 负责输出文件、元数据写回、EXIF 方向一致性
- 人像候选修复、评分、回退，以及修复后安全检查都在这里汇总并写回 `RepairRecord`
- cleanup candidate 强制尝试修复、结果分类和“仍不适合保存”回退也在这里完成
- `perf_timings` 记录生成方案、读取图片、候选生成/评分、保存输出和元数据保留等阶段耗时。

## 文件与元数据

### [file_actions.py](/E:/aitools/shapeyourphoto/file_actions.py)

- 文件夹扫描
- 扫描模式、忽略前缀与跳过目录统计
- 清理列表导出
- 清理候选移动
- 修复输出路径生成

### [app_settings.py](/E:/aitools/shapeyourphoto/app_settings.py)

- 扫描忽略目录前缀的持久化设置

### [metadata_utils.py](/E:/aitools/shapeyourphoto/metadata_utils.py)

- 读取并整理右侧元数据展示内容

### [drag_drop.py](/E:/aitools/shapeyourphoto/drag_drop.py)

- Windows 文件拖拽支持
- 属于平台相关高风险模块

### [preview_cache.py](/E:/aitools/shapeyourphoto/preview_cache.py)

- 缩略图缓存

## 进度与数据

### [progress_dialog.py](/E:/aitools/shapeyourphoto/progress_dialog.py)

- 统一进度控制器
- 扫描、分析、修复共用

### [stats_store.py](/E:/aitools/shapeyourphoto/stats_store.py)

- 本地统计持久化
- 默认写入 `usage_stats.json`

### [models.py](/E:/aitools/shapeyourphoto/models.py)

- 数据结构定义
- 新增字段时优先从这里统一设计

### [similar_review_dialog.py](/E:/aitools/shapeyourphoto/similar_review_dialog.py)

- 相似组列表窗口和组内对比窗口。
- 组内对比窗口的图片区可滚动，底部全局操作区固定；每图“删除此图”按钮必须保持可达。
- 修改窗口尺寸、分页或卡片布局时，要验证 2、3、4、5+ 张路径下按钮不被遮挡。

## 项目元信息

### [app_metadata.py](/E:/aitools/shapeyourphoto/app_metadata.py)

- 程序名、版本号、应用 ID、内置历史

### [CHANGELOG.md](/E:/aitools/shapeyourphoto/CHANGELOG.md)

- 版本历史
- 旧版本记录不应删除
## 1.1.3 Maintenance Addendum

以下内容保留为 1.1.3 的历史基线说明；如与 1.1.4 行为冲突，以后续 1.1.4 附录和 `docs/updates/1.1.4.md` 为准。

### `analyzer.py`

- 现同时输出 `raw_face_candidates`、`validated_face_boxes`、`face_candidates` 和 `cleanup_candidates`。
- 新增 `portrait_out_of_focus` 判断，重点关注 validated face / subject 与背景的清晰度差。

### `ui_app.py`

- 新增单独的 cleanup candidate 框体与独立勾选状态。
- cleanup 候选默认不勾选，且删除按钮只在有勾选时启用。

### `file_actions.py`

- 清理动作统一走安全出口：优先系统回收站，失败时回退到 `_cleanup_candidates` 隔离目录。
## 1.1.4 Maintenance Addendum
### Settings and Detail Panel Addendum
- `app_settings.py`
  - 现在负责统一的默认值、校验、读写、自动创建和损坏回退。
  - 当前管理扫描忽略目录前缀、默认扫描模式和修复完成详情默认筛选。
- `settings_dialog.py`
  - 统一“应用设置”对话框。
  - 提供忽略前缀增删、恢复默认、默认扫描模式和修复完成详情默认筛选配置。
- `scan_summary_dialog.py`
  - 展示最近一次扫描的聚合摘要和跳过目录滚动明细。
- `repair_completion_dialog.py`
  - 已从纯文本详情升级为带筛选的结果窗口。
  - 支持“已修复 / 已跳过 / 失败 / 强制尝试但未保存 / 强制尝试后保存 / 不适合保留相关 / 候选回退 / no-op”等筛选。

### 分析包结构

- `analyzer.py`
  - 保留对外兼容的 `analyze_image()` 与 `is_supported_image()` 入口。
  - 新逻辑已转发到 `analysis/` 包，避免旧调用链失效。
- `analysis/core.py`
  - 主分析流程。
  - 负责基础统计、场景分类、问题生成、指标组装和 `AnalysisResult` 回填。
- `analysis/portrait.py`
  - 负责人脸候选生成、真实人脸验证、背身/侧背身/画作脸识别，以及 portrait-aware 区域构建。
- `analysis/discard.py`
  - 负责通用 cleanup candidate 生成，不再把“建议删除”耦合在人像虚焦逻辑中。
- `analysis/common.py`
  - 存放共享的统计、掩膜、性能计时和文案兜底工具。
- `gpu_accel.py`
  - 检测可选 GPU 后端（CuPy、OpenCV-CUDA、torch CUDA），并给出 CPU 回退原因；不得成为启动必需依赖。
- `app_settings.py` / `settings_dialog.py`
  - 持久化应用设置、扫描偏好、修复详情筛选、分析并发模式与 GPU 加速模式。

### 修复计划与执行

- `repair_planner.py`
  - 现在会按单图生成 `RepairPlan`，包含 `method_ids`、`op_strengths`、`policy` 与 `notes`。
  - 手动模式也允许按图限幅，避免一刀切强修。
- `repair_engine.py`
  - 负责单图候选生成、评分、回退、元数据保留与保存输出。
  - 场景图和人像图现在分别走不同的候选选择逻辑。
- `repair_ops.py`
  - `recover_highlights()` 对不可恢复高光更保守，避免天空/白墙压灰。
  - `lift_shadows()` 对窗景、剪影、低调氛围强限幅。
  - `boost_vibrance()` 与 `reduce_saturation()` 会按 `color_type` 做保护。

### UI 与批量结果

- `ui_app.py`
  - 主缩略图列表与 cleanup 候选列表都支持多选。
  - 批量分析、批量修复、Console 刷新与进度回调都经过主线程调度。
  - 主菜单新增“不适合保留候选”复开入口。
- `repair_completion_dialog.py`
  - 负责可滚动的批量修复完成详情，不再把长文本塞入普通 `messagebox`。
- `cleanup_review_dialog.py`
  - 负责本轮 cleanup candidate 的独立复核窗口，默认不勾选任何图片。
## 1.1.4 Similar Images Addendum

### Similar Images Fix

- `similar_detector.py` 现在使用多尺度中心裁切、旋转鲁棒哈希、场景/主体摘要、边缘摘要、文件编号连续性和可靠时间辅助，支持 `high` / `medium` / `low` 三档相似组。
- `similar_review_dialog.py` 修复相似组列表布局：canvas 列表区域可真正滚动，底部按钮固定，组卡片按内容自然高度显示；筛选支持低置信候选。
- 检测仍然只输出批次级 `SimilarImageGroup`，不修改单张 `AnalysisResult` 和 cleanup candidate。

### [similar_detector.py](/E:/aitools/shapeyourphoto/similar_detector.py)

- 分析批次完成后的相似图片检测模块。
- 只读取缩略图级特征：aHash、dHash、颜色/亮度直方图、低分辨率灰度结构、尺寸比例和可靠拍摄时间。
- 接收批次 `perf_timings`，记录 feature extract、candidate pair build、pair compare、group build 与 total similar detection 耗时。
- 输出批次级 `SimilarImageGroup`，不修改单张 `AnalysisResult`。
- 100 张以内可直接做轻量特征对比；更大批次通过哈希、尺寸和时间分桶减少候选对。

### [similar_review_dialog.py](/E:/aitools/shapeyourphoto/similar_review_dialog.py)

- 相似组列表窗口和组内对比窗口。
- 列表窗口支持滚动、筛选、多选和“开始抉择”。
- 对比窗口按组逐个处理，2-4 张使用网格，更多图片分页显示；删除按钮回调主应用的安全删除逻辑。

### [models.py](/E:/aitools/shapeyourphoto/models.py)

- 新增 `SimilarImageGroup`，用于保存相似组编号、路径列表、相似度、等级、依据和可能连拍标记。
- 该结构属于分析批次附加结果，不进入单张图片的质量问题或修复策略字段。
# 1.1.5 Performance Module Addendum

- `benchmark_test_images.py`: local-only `/test` benchmark runner. It skips safely when no local photos exist and reports wall time, worker cumulative time, queue/wait time, slow stages, slow images, similar detection time, issue count, and cleanup candidate count.
- `app_settings.resolve_analysis_worker_plan()`: central source of truth for analysis worker mode, requested workers, actual workers, and cap reason.
- `analysis/core.py`: large images use a bounded working image for heavy numeric analysis, then return dimensions and analysis regions in original-image coordinates. `perf_timings` includes resize and existing stage timings.
- `similar_detector.py`: feature extraction can use Pillow JPEG `draft()` to avoid decoding full-size images for small hash/vector features.
- `ui_app.py`: Console batch rollups distinguish `wall_time` from `worker_cumulative_time` and keep Tk updates on the main thread.
- `gpu_accel.py`: optional backend detection and CPU fallback only; no required GPU dependency and no claimed default GPU offload.
