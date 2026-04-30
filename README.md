# 图片质量分析、修复与清理工具

这是一个面向 Windows 的本地图像分析与修复工具，提供图形界面、一键启动、目录扫描、逐张分析、自动修复、批量修复、勾选清理和累计统计。

## 当前能力

- 识别 `过曝`
- 识别 `欠曝`
- 识别 `失焦/模糊`
- 识别 `低对比度`
- 识别 `偏色`
- 识别 `噪点偏高`
- 识别 `层次不足`
- 识别 `色彩寡淡`
- 识别 `饱和度偏高`
- 分析阶段显示真实进度，包括目录扫描进度、批量张数进度和单张图片内部阶段进度
- 左侧列表支持缩略图、滚动条、排序、单击切换处理状态、右键移出列表
- 支持单张图片导入、目录导入，以及 Windows 原生拖入多张图片或目录
- 右侧采用四区布局：预览图、指标条图、诊断建议、属性与 Console
- 修复强度按当前图片的检测结果自动计算，不同图片会使用不同修复量
- 修复输出支持保留 EXIF、DPI、ICC Profile 和可用 XMP
- 修复对话框支持使用后缀、关闭后缀、覆盖原文件三种输出方式
- 累计统计会持久化到本地，重新打开程序后继续累计

## 启动方式

双击：

- `start_app.bat`
- `start_app.vbs`

命令行：

```powershell
python app.py
```

## 使用说明

1. 选择一个目录，或直接选择单张图片。
2. 也可以把图片或目录直接拖入主窗口。
3. 目录扫描时会弹出独立进度框，显示当前扫描文件和已发现图片数。
4. 左侧列表中，新导入图片默认标记为 `已选`。
5. `分析选中` 会优先分析所有 `已选` 项；如果没有 `已选` 项，则回退为当前高亮项。
6. 右侧预览区会同步展示分析标签、关键指标、诊断说明和属性信息。
7. `修复当前` 和 `批量修复勾选` 会根据检测结果自动选择合适的修复算法，并按问题程度计算不同强度。
8. `累计统计` 可查看累计分析量、修复量、问题检出率，并导出 CSV 报表。

## 元数据与签名说明

- 修复后的 JPG/PNG 会写入 `Software`、`Author`、`ImageDescription` 等修改来源信息。
- Description / Title 会尽量写入为 `原文件名 + Modified by ...` 形式。
- DPI 会尽量沿用原图设置，不会主动把 300 DPI 改成 96 DPI。
- ICC Profile 和可用 XMP 会尝试原样保留。
- Windows 文件属性里的 `Digital Signatures` 页不是普通 EXIF/XMP 元数据。当前程序会写入可追踪的元数据标记，但不会生成 Windows 代码签名式的真正数字签名页。

## HDR 说明

- 当前流程会尽量保留 ICC、XMP、EXIF 和 DPI。
- 如果原图属于常规 JPG 中封装的 HDR 或扩展色彩信息，程序会尽量保留可由 Pillow 回传的元数据。
- 对于依赖专有增益图、厂商扩展容器或系统级 Ultra HDR 结构的内容，是否能完全原样保留取决于底层库能否完整读写该结构。

## 水印说明

- 默认修复流程不会在右下角叠加可见水印。
- 项目里仍然保留了独立的叠加签名模块，后续如需启用，可以单独接入，不影响当前默认输出。

## 依赖

- `Python 3.10+`
- `Pillow`
- `NumPy`

安装：

```powershell
python -m pip install pillow numpy
```

## 主要文件

- [app.py](/E:/aitools/codexAuto_photosAnalyzer/app.py)
- [ui_app.py](/E:/aitools/codexAuto_photosAnalyzer/ui_app.py)
- [analyzer.py](/E:/aitools/codexAuto_photosAnalyzer/analyzer.py)
- [repair_engine.py](/E:/aitools/codexAuto_photosAnalyzer/repair_engine.py)
- [repair_ops.py](/E:/aitools/codexAuto_photosAnalyzer/repair_ops.py)
- [repair_dialog.py](/E:/aitools/codexAuto_photosAnalyzer/repair_dialog.py)
- [progress_dialog.py](/E:/aitools/codexAuto_photosAnalyzer/progress_dialog.py)
- [drag_drop.py](/E:/aitools/codexAuto_photosAnalyzer/drag_drop.py)
- [metadata_utils.py](/E:/aitools/codexAuto_photosAnalyzer/metadata_utils.py)
- [app_console.py](/E:/aitools/codexAuto_photosAnalyzer/app_console.py)
- [watermark_signature.py](/E:/aitools/codexAuto_photosAnalyzer/watermark_signature.py)
- [MODULES.md](/E:/aitools/codexAuto_photosAnalyzer/MODULES.md)
- [CHANGELOG.md](/E:/aitools/codexAuto_photosAnalyzer/CHANGELOG.md)

Copyright (c) 2026 Francis Zhang & Helloalp. All rights reserved. No permission is granted to use, copy, modify, or distribute this project without explicit written permission.
