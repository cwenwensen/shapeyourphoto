# Performance And Concurrency

## 线程模型

- Tk 控件只能在主线程更新。
- 目录扫描、批量分析、批量修复和相似检测可在后台线程运行。
- 后台线程只提交结果、日志或状态；UI 刷新通过主线程调度。
- 输出路径生成和文件保存要考虑并发冲突，不能绕开现有锁。

## worker 规划

分析 worker 数由 `app_settings.resolve_analysis_worker_plan()` 统一决定：

- `auto`：默认保守自动模式。
- `low`：低并发。
- `medium`：平衡模式。
- `high`：激进模式。
- `custom`：用户自定义，并受校验上限限制。

Console 和 benchmark 应同时显示 requested workers、actual workers 和限制原因。

## 取消与旧结果防护

批量分析使用 run_id + cancel_event：

- run_id 防止旧轮次结果写回。
- cancel_event 表示本轮已取消。
- 取消后 UI 立即恢复可操作状态，同时清空本轮目标结果。
- 后台 worker 的迟到结果必须丢弃。

## Console 合并刷新

Console 文本框不应每条日志都重绘。当前策略是日志进入 `AppConsole` 缓存，UI 用短延迟合并刷新。维护时不得恢复成后台 worker 高频直接写 Text 控件。

## perf_timings / perf_notes

- 阶段耗时统一用 `perf_timings`，单位为毫秒。
- `perf_notes` 写用户/维护者可读瓶颈提示。
- 分析和修复的慢阶段应在批量摘要中聚合为 top slow steps。
- Console 以 wall time 为主，worker cumulative 只作为并发诊断。

## GPU fallback

[gpu_accel.py](/E:/aitools/shapeyourphoto/gpu_accel.py) 当前只检测可选后端并返回状态文案：

- CuPy CUDA
- OpenCV CUDA
- torch CUDA

无论 GPU 设置为关闭、自动或开启，缺少后端时都必须安全回退 CPU。除非未来有 `/test` 真实样张证明数据搬运收益，否则不要声称默认 GPU offload 已启用。
