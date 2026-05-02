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
- 输出 `AnalysisResult`

### [repair_planner.py](/E:/aitools/shapeyourphoto/repair_planner.py)

- 把问题标签映射到修复方法

### [repair_ops.py](/E:/aitools/shapeyourphoto/repair_ops.py)

- 各类具体修复算子
- 修改这里时要重点关注视觉副作用

### [repair_engine.py](/E:/aitools/shapeyourphoto/repair_engine.py)

- 执行修复链
- 负责输出文件、元数据写回、EXIF 方向一致性

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
