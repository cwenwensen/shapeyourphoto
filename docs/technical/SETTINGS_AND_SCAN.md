# Settings And Scan

## 设置来源

[app_settings.py](/E:/aitools/shapeyourphoto/app_settings.py) 是应用设置的唯一数据入口，负责：

- `settings_schema_version`。
- 默认值。
- 读写 `app_settings.json`。
- 缺失自动创建。
- 损坏备份和回退默认值。
- 所有字段规范化。
- `migrate_settings(old_version, data)` 迁移入口。

[settings_dialog.py](/E:/aitools/shapeyourphoto/settings_dialog.py) 是统一 UI 入口。不要新增零散设置菜单项。

## 当前设置

- `settings_schema_version`：当前为 `1`，保存时自动写入。
- 扫描忽略目录前缀。
- 默认扫描模式。
- 修复完成详情默认筛选。
- 分析并发模式。
- 自定义 worker 数。
- GPU 加速模式。

旧设置缺少 schema version、缺字段、字段类型错误或含未知字段时，应由 `validate_settings_payload()` 和 `migrate_settings()` 规范化。UI 不直接处理 JSON 细节。

## 扫描模式

- `ask`：每次询问。
- `all`：扫描全部，包含子目录。
- `current_only`：只扫描当前目录。
- `subdirs_only`：只扫描所有子目录。

扫描范围选择窗口必须适配小屏和系统缩放，底部取消按钮可达。

## 忽略前缀

默认至少包含 `_repair`。任何以 `_repair` 开头的目录都会在根目录和任意子目录层级整体跳过，例如：

- `_repair`
- `_repair_old`
- `_repair_2026`
- `_repaired`

用户可补充其他前缀，但规范化后仍必须保留 `_repair`。

## 扫描摘要

`file_actions.ScanSummary` 记录：

- root
- mode
- imported_count
- visited_files
- ignored_prefixes
- skipped_details

Console 只输出摘要；完整跳过路径、命中前缀、原因和层级位置由 `scan_summary_dialog.py` 展示。

## 回归入口

修改扫描逻辑时至少检查：

- 按钮选择目录。
- 拖拽文件夹。
- 批量分析前补扫。
- 默认扫描模式。
- 自定义忽略前缀。
- `_repair*` 任意层级跳过。
