# Maintenance Guide

## 维护原则

1. 优先恢复和保持稳定可用性。
2. 不大改架构，不换技术栈，不引入重依赖。
3. 先看代码、运行结果和 diff，再看 handover。
4. 修复必须可验证，不能只停留在解释层面。

## 文本编码与乱码排查

- 如果应用内分析结果出现乱码，优先怀疑源码里的用户可见文案常量已经损坏，而不只是查看器编码设置异常。
- 优先用 `python` 以 `utf-8` 读取文件内容确认真实文本，不要只依赖 PowerShell 控制台显示，因为控制台代码页可能把正常中文显示成乱码或问号。
- `analyzer.py` 已增加问题文案兜底回退：当 `Issue.label`、`Issue.detail` 或 `Issue.suggestion` 检测到疑似乱码时，会按 `issue.code` 回退到可读描述，避免异常文本直接进入 UI。
- 修复乱码时要同时处理两层：
  - 第一层是把损坏的源码常量改回正常中文；
  - 第二层是保留兜底回退，避免后续新增问题类型时再次把损坏文案直接暴露给用户。
- 如果必须通过脚本批量改写中文常量，优先使用 UTF-8 安全的编辑方式；当当前终端代码页不可靠时，可用 Unicode 转义写回源码，避免中文在脚本输入阶段被替换成 `?`。

## 方向归一与 EXIF

- 修复链路读取图片时已经通过 `ImageOps.exif_transpose` 把像素方向转正，因此保存输出时不能再原样写回旧的 `Orientation` 标签。
- JPEG / WebP 保存前应把 EXIF `Orientation` 归一为 `1`，否则会出现“像素已转正，但查看器又按旧标签再次旋转”的双重旋转问题。
- 回归验证时至少检查三项：
  - 原图 `size` 与 `Orientation`
  - 修复输出的物理尺寸是否已经转正
  - 修复输出的 `Orientation` 是否为 `1`

## 高风险修改点

### 启动链路

- `start.bat`
- `start_app.bat`
- `app.py`
- `app.pyw`

注意：

- 日常启动不得自动安装依赖
- 启动脚本应尽量短、快、稳

### 主界面链路

- `ui_app.py`
- `drag_drop.py`
- `progress_dialog.py`
- `debug_open_dialog.py`

注意：

- Tk 的 UI 更新必须回到主线程
- 目录扫描、分析、修复都要避免阻塞主线程
- 拖拽是 Windows 相关逻辑，修改后必须重点验证
- 调试模式如涉及打开文件，应避免阻塞主界面

### 图像修复链路

- `analyzer.py`
- `repair_planner.py`
- `repair_ops.py`
- `repair_engine.py`

注意：

- 视觉判断不能只靠单一全局统计
- 修复前后朝向必须一致
- 输出后 EXIF 与像素朝向要匹配
- 元数据保留要谨慎

## 推荐验证顺序

1. 双击 [start.bat](/E:/aitools/shapeyourphoto/start.bat) 能快速启动
2. 选择单张图片能进入等待列表
3. 选择目录能完成扫描，不假死
4. 拖拽图片能入列
5. 单图分析进度能真实推进
6. 批量分析进度能真实推进
7. 修复弹窗底部按钮完整可见
8. 修复输出方向与原图显示方向一致
9. 修复结果视觉上没有明显副作用
10. 调试模式关闭时，修复流程与原先一致
11. 调试模式开启时，只弹出本轮成功修复的前后对比打开窗口

## 修改文档的要求

- 功能变化后，应同步更新 `docs/`
- 版本变化后，应同步更新 [CHANGELOG.md](/E:/aitools/shapeyourphoto/CHANGELOG.md) 和 [app_metadata.py](/E:/aitools/shapeyourphoto/app_metadata.py)
- 不要留下临时 handover 垃圾文档
