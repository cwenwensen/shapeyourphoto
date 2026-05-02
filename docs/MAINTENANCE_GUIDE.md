# Maintenance Guide

## 维护原则

1. 优先恢复和保持稳定可用性。
2. 不大改架构，不换技术栈，不引入重依赖。
3. 先看代码、运行结果和 diff，再看 handover。
4. 修复必须可验证，不能只停留在解释层面。

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
