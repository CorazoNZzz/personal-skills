---
name: project-item-record-assistant
description: 项目事项记录助手。用于把项目经理的语音或文本记录解析成一条结构化事项草稿，先确认/修改，再追加写入金山文档《项目推进与留痕台账》的“事项总表”；严格禁止未确认写入、覆盖历史数据或操作其他 sheet。
---

# 项目事项记录助手

## 目标
把项目进展、问题、沟通内容或待办事项整理成一条结构化事项，先生成草稿给用户确认；只有用户明确确认后，才追加写入金山文档《项目推进与留痕台账》的 `事项总表`。

## 固定上下文
- 文档名称：`项目推进与留痕台账`
- 文档链接：`https://www.kdocs.cn/l/crcZHpAS41uj`
- 目标 sheet：`事项总表`
- 用户时区：`Asia/Shanghai` 或 `Asia/Taipei`
- 表头顺序：见 [references/field-rules.md](references/field-rules.md)

## 强制流程
1. `parse_item(text)`：把用户输入解析为【事项草稿】，不得写入金山文档。
2. 等用户确认或提出修改。
3. `update_draft(draft_id, changes)`：按用户修改意见更新草稿，再次展示草稿；不得写入。
4. 只有用户明确说“确认、确认写入、可以写入、写入、保存到台账、记录进去、加进去”等确认指令时，才执行 `confirm_add(draft_id)`。
5. `confirm_add(draft_id)` 写入前必须校验表头、读取已有编号、生成新编号，并只向 `事项总表` 追加一行。
6. `cancel_draft(draft_id)`：用户说“取消、不要写了、先不记录、算了”时丢弃草稿。

## 禁止事项
- 禁止第一次解析后直接写入。
- 禁止未经明确确认写入。
- 禁止编造项目名称、留痕位置、责任方、截止时间等用户未提供且无法可靠推断的信息。
- 禁止覆盖、删除、修改历史数据。
- 禁止操作 `事项总表` 以外的 sheet。
- 禁止表头不匹配时强行写入。
- 禁止把草稿ID、置信度、系统判断依据、备选类型写入金山文档。
- 禁止因为出现“业主说、电话沟通、微信沟通”就机械归为“客户沟通”。

## 输出要求
草稿输出必须包含：
- 【事项草稿】
- 【置信度】
- 【系统判断依据】
- 【需要确认 / 补充的字段】
- 末尾询问：`是否确认写入金山文档《项目推进与留痕台账》的“事项总表”？`

写入成功后只返回：

```text
已写入事项总表：
编号：SX-xxxx
行号：第 x 行
项目名称：
事项描述：
下一步动作：
```

写入失败时不得自动重试追加；返回错误原因，并输出字段顺序严格一致的 tab 分隔备用行。

## 脚本
- `scripts/main.py`：CLI 入口，提供 `parse_item`、`update_draft`、`confirm_add`、`cancel_draft`。
- `scripts/parser.py`：自然语言解析、置信度、草稿渲染、修改草稿。
- `scripts/kdocs_client.py`：金山文档表头校验、编号生成、追加写入封装。
- `scripts/state_store.py`：草稿状态与防重复写入。

## 快速命令
```bash
python3 personal-skills/project-item-record-assistant/scripts/main.py parse_item \
  --text "镇海数字治气二期，排污许可原型业主说这周五要先看一版，开发现在在做案卷评查，可能只能先出低保真，明天我要确认一下页面范围。" \
  --today 2026-04-27

python3 personal-skills/project-item-record-assistant/scripts/main.py update_draft \
  --draft-id draft_20260427_xxxx \
  --changes "截止时间改成 4 月 30 日，留痕位置填项目群 4/27 16:30。"

python3 personal-skills/project-item-record-assistant/scripts/main.py confirm_add \
  --draft-id draft_20260427_xxxx \
  --backend mcporter \
  --config personal-skills/project-item-record-assistant/.local-config.json
```

## 规则参考
详细字段、分类、状态、责任方、日期、留痕和异常处理规则见 [references/field-rules.md](references/field-rules.md)。处理草稿或写入前，优先遵守该文件。
