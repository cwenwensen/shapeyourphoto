# ShapeYourPhoto

图片质量分析、修复与清理工具。当前版本：`1.1.6`。

ShapeYourPhoto 是一个面向 Windows 桌面使用的本地图像工具，支持图片导入、目录扫描、批量分析、自动/手动修复、不适合保留候选复核、相似图片复核删除、累计统计和本地性能基准。项目默认离线运行，不上传用户图片。

## 当前主路径

1. 通过 `start.bat`、`start_app.bat`、`start_app.vbs` 或 `python app.py` 启动。
2. 选择图片、选择目录，或把图片/文件夹拖入主窗口。
3. 图片进入左侧主列表；单张图片也是加入主列表处理，不再存在独立单图窗口。
4. 点击“分析选中”或“分析全部”，后台线程池执行分析，Tk 控件更新回主线程。
5. 分析结果刷新右侧 HUD、指标条、诊断说明、属性和 Console。
6. 批次分析完成后，应用可生成 cleanup candidates 和批次级相似图片组。
7. 修复通过 `repair_planner.py` 和 `repair_engine.py` 生成单图自适应方案；降噪也在这条统一链路内执行。
8. 修复完成详情使用可筛选滚动窗口，不再用普通 `messagebox` 承载长结果列表。

## 当前能力

- 识别过曝、欠曝、失焦/模糊、低对比度、偏色、噪点偏高、层次不足、色彩寡淡、饱和度偏高等问题。
- 人像感知分析区分 raw face candidates、validated real faces、背身/侧背身人物、画作/海报脸和纹理误检。
- 场景字段包括 `scene_type`、`portrait_type`、`exposure_type`、`highlight_recovery_type`、`color_type`。
- cleanup candidate 默认不进入修复；只有在修复弹窗显式开启强制尝试后，才允许进入修复链，并仍会经过评分、安全检查和回退。
- 相似图片检测是分析批次的附加结果，只生成 `SimilarImageGroup`，不写回单张 `AnalysisResult`。
- 目录扫描支持默认扫描模式、四选项范围选择、忽略目录前缀和“最近扫描摘要”；默认跳过任意层级的 `_repair*` 输出目录。
- 性能审计通过 `perf_timings` / `perf_notes`、Console 摘要和 `/test` 本地 benchmark 维护。
- GPU 设置仅做可选后端检测和 CPU 回退提示；CUDA、CuPy、OpenCV-CUDA、torch CUDA 都不是硬依赖。

## 启动与依赖

日常启动：

```powershell
start.bat
```

命令行启动：

```powershell
python app.py
```

首次安装依赖：

```powershell
setup_deps.bat
```

依赖：

- `Python 3.10+`
- `Pillow`
- `NumPy`

## 文档阅读顺序

正式维护文档从 [docs/README.md](/E:/aitools/shapeyourphoto/docs/README.md) 开始。建议顺序：

1. [docs/PRESERVATION_RULES.md](/E:/aitools/shapeyourphoto/docs/PRESERVATION_RULES.md)
2. [docs/SYSTEM_OVERVIEW.md](/E:/aitools/shapeyourphoto/docs/SYSTEM_OVERVIEW.md)
3. [docs/MODULE_REFERENCE.md](/E:/aitools/shapeyourphoto/docs/MODULE_REFERENCE.md)
4. [docs/UI_AND_WORKFLOWS.md](/E:/aitools/shapeyourphoto/docs/UI_AND_WORKFLOWS.md)
5. [docs/MAINTENANCE_GUIDE.md](/E:/aitools/shapeyourphoto/docs/MAINTENANCE_GUIDE.md)
6. [docs/technical/README.md](/E:/aitools/shapeyourphoto/docs/technical/README.md)
7. [docs/updates/README.md](/E:/aitools/shapeyourphoto/docs/updates/README.md)

根目录 [MODULES.md](/E:/aitools/shapeyourphoto/MODULES.md) 是快速模块索引；更完整说明以 `docs/` 为准。旧版本更新说明保留历史上下文，如与 1.1.6 当前文档冲突，以 1.1.6 文档和代码为准。

## 本地测试样张

`test/` 用于本地真实图片 benchmark 和回归检查。图片文件被 `.gitignore` 忽略，不应提交；只保留 [test/README.md](/E:/aitools/shapeyourphoto/test/README.md) 作为约定说明。

## 元数据与输出边界

- 修复输出尽量保留 EXIF、DPI、ICC Profile 和可用 XMP。
- 输出前会归一 EXIF Orientation，避免像素已转正但查看器再次旋转。
- 程序写入可追踪的图片元数据，不生成 Windows 文件属性里的真正代码签名页。
- 默认修复流程不叠加可见水印；`watermark_signature.py` 仅作为保留模块。

Copyright (c) 2026 Francis Zhang & Helloalp. All rights reserved. No permission is granted to use, copy, modify, or distribute this project without explicit written permission.
