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
- 目录扫描支持忽略目录前缀设置，并默认跳过所有 `_repair*` 目录
- 目录含子目录时可选择扫描全部、只扫当前目录、只扫所有子目录，或取消扫描
- 右侧采用四区布局：预览图、指标条图、诊断建议、属性与 Console
- 修复强度按当前图片的检测结果自动计算，不同图片会使用不同修复量
- cleanup candidate 默认不会进入修复；如需尝试，需在修复弹窗中显式开启“强制修复不值得保留的图片”
- 去噪已并入统一分析与修复链，会根据人像、夜景、纯净天空和建筑纹理等场景自动决定是否推荐与如何限幅
- 修复输出支持保留 EXIF、DPI、ICC Profile 和可用 XMP
- 修复对话框支持使用后缀、关闭后缀、覆盖原文件三种输出方式
- 累计统计会持久化到本地，重新打开程序后继续累计

## 启动方式

双击：

- `start.bat`
- `start_app.bat`
- `start_app.vbs`

命令行：

```powershell
python app.py
```

如需首次安装依赖，请单独运行：

```powershell
setup_deps.bat
```

## 维护文档

- 正式维护文档目录： [docs/README.md](/E:/aitools/shapeyourphoto/docs/README.md)
- 文档保留规则： [docs/PRESERVATION_RULES.md](/E:/aitools/shapeyourphoto/docs/PRESERVATION_RULES.md)
- 1.1.4 起，分析主逻辑已迁移到 [analysis/core.py](/E:/aitools/shapeyourphoto/analysis/core.py) 和 [analysis/portrait.py](/E:/aitools/shapeyourphoto/analysis/portrait.py)；[analyzer.py](/E:/aitools/shapeyourphoto/analyzer.py) 仅保留兼容入口。

后续接手时，请优先阅读 `docs/`，并保留该目录及其正式文档。

## 使用说明

1. 选择一个目录，或直接选择单张图片。
2. 也可以把图片或目录直接拖入主窗口。
3. 目录扫描时会弹出独立进度框；若目录包含子目录，还会先要求选择扫描范围。
4. 左侧列表中，新导入图片默认标记为 `已选`。
5. `分析选中` 会优先分析所有 `已选` 项；如果没有 `已选` 项，则回退为当前高亮项。
6. 右侧预览区会同步展示分析标签、关键指标、诊断说明、降噪建议和属性信息。
7. `修复当前` 和 `批量修复勾选` 会根据检测结果自动选择合适的修复算法，并按问题程度计算不同强度。
8. 如果图片被判定为“不值得保留”，默认不会进入修复；如需尝试，需在修复弹窗中显式开启强制尝试，但仍可能因为评分或安全检查失败而不保存输出。
9. `累计统计` 可查看累计分析量、修复量、问题检出率，并导出 CSV 报表。

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

- [app.py](/E:/aitools/shapeyourphoto/app.py)
- [ui_app.py](/E:/aitools/shapeyourphoto/ui_app.py)
- [analyzer.py](/E:/aitools/shapeyourphoto/analyzer.py)
- [analysis/core.py](/E:/aitools/shapeyourphoto/analysis/core.py)
- [analysis/portrait.py](/E:/aitools/shapeyourphoto/analysis/portrait.py)
- [repair_planner.py](/E:/aitools/shapeyourphoto/repair_planner.py)
- [repair_engine.py](/E:/aitools/shapeyourphoto/repair_engine.py)
- [repair_ops.py](/E:/aitools/shapeyourphoto/repair_ops.py)
- [repair_dialog.py](/E:/aitools/shapeyourphoto/repair_dialog.py)
- [repair_completion_dialog.py](/E:/aitools/shapeyourphoto/repair_completion_dialog.py)
- [cleanup_review_dialog.py](/E:/aitools/shapeyourphoto/cleanup_review_dialog.py)
- [progress_dialog.py](/E:/aitools/shapeyourphoto/progress_dialog.py)
- [drag_drop.py](/E:/aitools/shapeyourphoto/drag_drop.py)
- [metadata_utils.py](/E:/aitools/shapeyourphoto/metadata_utils.py)
- [app_console.py](/E:/aitools/shapeyourphoto/app_console.py)
- [watermark_signature.py](/E:/aitools/shapeyourphoto/watermark_signature.py)
- [MODULES.md](/E:/aitools/shapeyourphoto/MODULES.md)
- [CHANGELOG.md](/E:/aitools/shapeyourphoto/CHANGELOG.md)

Copyright (c) 2026 Francis Zhang & Helloalp. All rights reserved. No permission is granted to use, copy, modify, or distribute this project without explicit written permission.

## 1.1.4 当前维护说明

- 当前以主列表工作流为准，独立“单图模式”已移除；保留的是“选择单张图片加入主列表”。
- 旧的“去噪当前”孤立入口已移除，降噪统一通过分析、修复规划和修复执行链处理。
- 扫描相关设置现统一收敛到“设置 -> 应用设置”，不再以零散菜单项继续扩张。
- 扫描完成后如需追踪被跳过的目录，请使用“最近扫描摘要”查看按前缀聚合统计和完整跳过明细。
- 修复完成详情已改为可筛选的滚动窗口，不再以普通 messagebox 承载长结果列表。
