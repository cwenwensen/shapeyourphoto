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

### [single_image_window.py](/E:/aitools/shapeyourphoto/single_image_window.py)

- 单图模式窗口入口

### [history_dialog.py](/E:/aitools/shapeyourphoto/history_dialog.py)

- 版本历史窗口

### [stats_dialog.py](/E:/aitools/shapeyourphoto/stats_dialog.py)

- 统计信息窗口

### [repair_dialog.py](/E:/aitools/shapeyourphoto/repair_dialog.py)

- 修复方案选择弹窗
- 底部操作按钮可见性很重要

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

### [repair_ops.py](/E:/aitools/shapeyourphoto/repair_ops.py)

- 各类具体修复算子
- 修改这里时要重点关注视觉副作用
- `lift_shadows` 现包含人像主体与暗背景保护逻辑
- 新增基于粗 mask 的人像局部增强与高调背景保护能力

### [repair_engine.py](/E:/aitools/shapeyourphoto/repair_engine.py)

- 执行修复链
- 负责输出文件、元数据写回、EXIF 方向一致性
- 人像候选修复、评分、回退，以及修复后安全检查都在这里汇总并写回 `RepairRecord`

## 文件与元数据

### [file_actions.py](/E:/aitools/shapeyourphoto/file_actions.py)

- 文件夹扫描
- 清理列表导出
- 清理候选移动
- 修复输出路径生成

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
