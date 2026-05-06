---
name: project-item-record-assistant
description: 项目事项记录助手。用于把项目经理的语音或文本记录解析成一条结构化事项草稿，先确认/修改，再追加写入金山文档《项目推进与留痕台账》的"事项总表"；严格禁止未确认写入、覆盖历史数据或操作其他 sheet。
---

# 项目事项记录助手

## ⚠️ 踩坑记录（必读）

### 1. mcporter CLI 正确路径
```
/Users/corazon/Library/Application Support/QClaw/npm-global/lib/node_modules/mcporter/dist/cli.js
```
**不是** `npm-global/bin/mcporter`（那是软链接）。
版本：0.9.0，用 `node /path/to/cli.js --version` 确认。

### 2. mcporter call 正确格式
```bash
node /path/to/cli.js call kdocs-qclaw sheet.update_range_data \
  --args '{"file_id":"xxx","sheetId":2,"rangeData":[[...]],"rowFrom":N,"rowTo":N,"columnFrom":0,"columnTo":14,"opType":"formula"}'
```
- **用 `--args** 传递 JSON 对象**（不是 positional args）
- positional args `file_id=xxx` 会报 `tool not found` 或 400 错误
- 任何工具调用都要用 `--args` 包裹 JSON

### 3. `sheet.update_range_data` 写入实际值
- 工具 `sheet.update_range_data` 原设计是 formula/format/merge/picture，但 **可以写入实际值**
- 必须指定 `opType: "formula"`（不是 `insert`/`update`/`set`）
- 传二维数组 `[[val1, val2, ...]]` 作为 `rangeData`，不要逐格传

### 4. API 行号 vs 可见行号
- 金山文档 API 用 **0-based** 行号
- 可见行 1 = API row 0（标题）
- 可见行 2 = API row 1（表头）
- **可见行 3 = API row 2**（第一条数据）
- 常见错误：以为数据从 row 3 开始，实际 API row 2 才是第一条数据

### 5. 表头实际在 row 1（不是 row 2）
field-rules.md 说"默认第 2 行是字段表头"，**错误**。实际：
- API row 0：合并标题"事项总表"
- API row 1：字段表头（编号、日期、项目名称…共 15 列）
- API row 2 起：数据行

### 6. 不要试着用 skill CLI 的 write 命令
skill 的 CLI（`main.py`）只有 `parse_item / update_draft / confirm_add / cancel_draft`，**没有** `write` 子命令。直接用 `confirm_add` 写入。

### 7. SIGTERM 超时问题
长时间运行的进程（如读取整个 sheet）会被 SIGTERM 终止。分批写入（BATCH_SIZE=3）或设置更短超时。

### 8. 写草稿时 project_name 识别为"待确认"是正常的
自然语言解析置信度低时，草稿里 `project_name` 填"待确认"，等用户补充即可，不要自行编造。

---

## 固定上下文
把项目进展、问题、沟通内容或待办事项整理成一条结构化事项,先生成草稿给用户确认;只有用户明确确认后,才追加写入金山文档《项目推进与留痕台账》的 `事项总表`。

## 固定上下文
- 文档名称:`项目推进与留痕台账`
- 文档链接:`https://www.kdocs.cn/l/crcZHpAS41uj`
- 目标 sheet:`事项总表`
- 用户时区:`Asia/Shanghai` 或 `Asia/Taipei`
- 表头顺序:见 [references/field-rules.md](references/field-rules.md)

## 强制流程
1. `parse_item(text)`:把用户输入解析为【事项草稿】,不得写入金山文档。
2. 等用户确认或提出修改。
3. `update_draft(draft_id, changes)`:按用户修改意见更新草稿,再次展示草稿;不得写入。
4. 只有用户明确说"确认、确认写入、可以写入、写入、保存到台账、记录进去、加进去"等确认指令时,才执行 `confirm_add(draft_id)`。
5. `confirm_add(draft_id)` 写入前必须校验表头、读取已有编号、生成新编号,并只向 `事项总表` 追加一行。
6. `cancel_draft(draft_id)`:用户说"取消、不要写了、先不记录、算了"时丢弃草稿。

## 金山表格坐标
- OpenClaw kdocs `sheet.*` API 使用 0-based `rowFrom/colFrom`。
- 脚本对外展示和内部业务判断使用表格可见行号/列号(1-based),调用 API 前统一转换。
- 默认第 1 行是台账标题,第 2 行是字段表头,数据从第 3 行开始;如实际文档不同,使用 `header_row` 配置覆盖。
- 本台账是在线表格 `sheetType=et`,使用 `sheet.get_range_data` / `sheet.update_range_data`;不要用多维表格 `dbsheet.*` 写入。
- Token 只保存在 `mcporter` 的 `kdocs-qclaw` 配置中,不写入 `data/config.json`。

## 禁止事项
- 禁止第一次解析后直接写入。
- 禁止未经明确确认写入。
- 禁止编造项目名称、留痕位置、责任方、截止时间等用户未提供且无法可靠推断的信息。
- 禁止覆盖、删除、修改历史数据。
- 禁止操作 `事项总表` 以外的 sheet。
- 禁止表头不匹配时强行写入。
- 禁止把草稿ID、置信度、系统判断依据、备选类型写入金山文档。
- 禁止因为出现"业主说、电话沟通、微信沟通"就机械归为"客户沟通"。

## 输出要求
草稿输出必须包含:
- 【事项草稿】
- 【置信度】
- 【系统判断依据】
- 【需要确认 / 补充的字段】
- 末尾询问:`是否确认写入金山文档《项目推进与留痕台账》的"事项总表"?`

写入成功后只返回:

```text
已写入事项总表:
编号:SX-xxxx
行号:第 x 行
项目名称:
事项描述:
下一步动作:
```

写入失败时不得自动重试追加;返回错误原因,并输出字段顺序严格一致的 tab 分隔备用行。

## 脚本
- `scripts/main.py`:CLI 入口,提供 `parse_item`、`update_draft`、`confirm_add`、`cancel_draft`。
- `scripts/parser.py`:自然语言解析、置信度、草稿渲染、修改草稿。
- `scripts/kdocs_client.py`:金山文档表头校验、编号生成、追加写入封装。
- `scripts/state_store.py`:草稿状态与防重复写入。

## 快速命令（必须用完整路径）
```bash
python3 /Volumes/a盘/project/personal-skills/project-item-record-assistant/scripts/main.py parse_item \
  --text "镇海数字治气二期，排污许可原型业主说这周五要先看一版，开发现在在做案卷评查，可能只能先出低保真，明天我要确认一下页面范围。" \
  --today 2026-04-27

python3 /Volumes/a盘/project/personal-skills/project-item-record-assistant/scripts/main.py update_draft \
  --draft-id draft_20260427_xxxx \
  --changes "截止时间改成 4 月 30 日，留痕位置填项目群 4/27 16:30。"

python3 /Volumes/a盘/project/personal-skills/project-item-record-assistant/scripts/main.py confirm_add \
  --draft-id draft_20260427_xxxx \
  --backend mcporter
```

**不要用** 相对路径 `personal-skills/...`，要用完整路径。

## 规则参考
详细字段、分类、状态、责任方、日期、留痕和异常处理规则见 [references/field-rules.md](references/field-rules.md)。处理草稿或写入前,优先遵守该文件。
