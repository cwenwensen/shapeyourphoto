# Technical Docs

`docs/technical/` 用于存放技术维护文档、架构说明、模块说明、流程说明。

重要约束：

1. 后续接手的 agent 不得删除 `docs/technical/`。
2. 不得删除本目录中的正式技术文档，应通过补充、修订、迁移的方式维护。
3. 如果根目录 `docs/` 下已有正式技术文档，应继续保留，并在本目录建立分类索引。

当前技术文档入口：

- [系统总览](/E:/aitools/shapeyourphoto/docs/SYSTEM_OVERVIEW.md)
- [模块索引](/E:/aitools/shapeyourphoto/docs/MODULE_REFERENCE.md)
- [维护指南](/E:/aitools/shapeyourphoto/docs/MAINTENANCE_GUIDE.md)
- [界面与流程](/E:/aitools/shapeyourphoto/docs/UI_AND_WORKFLOWS.md)
- [保留规则](/E:/aitools/shapeyourphoto/docs/PRESERVATION_RULES.md)
- [人像感知分析](/E:/aitools/shapeyourphoto/docs/technical/PORTRAIT_AWARE_ANALYSIS.md)

建议：

- 新增技术专题时，优先在 `docs/technical/` 下新建文档。
- 涉及模块链路、线程、EXIF、修复算法、拖拽、进度等内容，都应归档到这里。
## 1.1.4 Addendum

- 1.1.4 起，分析器主体已迁移到 `analysis/` 包；如果需要补充分析链路、候选评分、清理候选或并发边界文档，优先在 `docs/technical/` 下新增专题，而不是只写在临时 handover 里。

## 1.1.5 Addendum

- 性能计时统一复用 `perf_timings` / `perf_notes`：分析阶段记录读取、基础统计、场景判断、人像/清晰度/噪声/色彩判断、cleanup candidate；修复阶段记录方案、读取、主要修复步骤、候选评分/安全检查、保存输出和元数据保留。
- `ui_app.py` 负责把这些计时压缩成 Console 可读摘要，并在批量结束时输出 top slow steps。不要在 Console 输出内部阈值或评分公式。
- Console Text 刷新已改为合并刷新，这是多线程收益的一部分；后续维护不要恢复为每条日志整块重绘。
- 相似组内对比窗口属于 UI 布局修复，不改变 `similar_detector.py` 的检测算法；相关验证以按钮可见性和最小窗口路径为主。
- 1.1.5 起，批次性能审计还记录 worker 排队等待、worker wall time、总 wall time、相似检测分段、UI 行更新和 Console flush 耗时，用于判断低 CPU 利用率来自并发、GIL/CPU 阶段、IO、主线程刷新还是相似检测。
- 分析并发配置集中在 `app_settings.py` / `settings_dialog.py`，不要新增零散菜单项。默认自动模式必须保守，避免大图批量分析时内存暴涨。
- GPU 检测集中在 `gpu_accel.py`，只允许可选依赖探测和安全 CPU 回退；真正接入 GPU 数值阶段前，需要证明数据搬运成本低于收益。
# 1.1.5 Real-Image Performance Addendum

- See [Performance benchmarks and /test real-image workflow](/E:/aitools/shapeyourphoto/docs/technical/PERFORMANCE_BENCHMARKS.md).
- `/test` is reserved for local real photos and must not commit image files.
- Console summaries must distinguish `wall_time` from `worker_cumulative_time`; the latter is cumulative worker effort, not user waiting time.
- Worker settings must flow through `resolve_analysis_worker_plan()` and report requested vs actual workers.
- GPU remains optional detection and CPU fallback unless a future backend proves real offload wins on `/test`.
