# 项目事项记录助手

这是一个 QClaw / OpenClaw Skill，用于把项目经理的语音或文本记录整理为一条结构化事项草稿，并在确认后追加写入金山文档《项目推进与留痕台账》的 `事项总表`。

## 四个动作

```bash
python3 scripts/main.py parse_item --text "事项内容"
python3 scripts/main.py update_draft --draft-id draft_xxxx --changes "截止时间改成 4 月 30 日"
python3 scripts/main.py confirm_add --draft-id draft_xxxx --backend mcporter --config .local-config.json
python3 scripts/main.py cancel_draft --draft-id draft_xxxx
```

## 金山文档配置

优先使用 QClaw / OpenClaw 官方 connector 或 `mcporter` 的 `kdocs` server。`.local-config.json` 示例：

```json
{
  "file_id": "金山文档 file_id",
  "drive_id": "",
  "sheet_id": "事项总表 sheetId",
  "header_row": 2,
  "max_scan_rows": 1000,
  "api_index_base": 0,
  "mcporter_cli": "/Users/corazon/Library/Application Support/QClaw/npm-global/node_modules/mcporter/dist/cli.js"
}
```

说明：
- `header_row` 默认第 2 行，用于兼容第 1 行是表名称、第 2 行才是字段表头的台账。
- `api_index_base` 固定为 `0`；OpenClaw kdocs `sheet.*` API 的 `rowFrom/colFrom` 是 0-based。
- 脚本对外返回的行号仍是表格里看到的行号，例如写入第 3 行时 API 使用 `rowFrom=2`。

确认写入时脚本会校验表头、读取已有编号、生成 `SX-xxxx`，并严格按 15 个字段追加到最后一行。没有配置 connector 时不会写入，会输出 tab 分隔备用行。
