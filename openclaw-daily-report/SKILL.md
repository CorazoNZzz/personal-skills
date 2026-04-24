---
name: openclaw-daily-report
description: 将自然语言工作内容自动转换为“日报管理-日报列表-新增日报”的可提交数据，并通过项目管理系统日报 API 自动提交。用户提到“写日报/补日报/提交日报/工时分配/学习或其他”等场景时使用；严格执行提交前校验：今日进展与工时必须同时填写、总工时不少于8小时、不在项目列表中的内容归入“学习或其他”。
---

# OpenClaw 日报自动填报

## 目标
把用户一句话或一段话中的当日工作拆分为日报条目，自动完成项目匹配、工时分配、规则校验，并调用后端提交。

## 运行前提（必须）

1. 必须有可用的 `api_base`（例如 `https://xxx/api` 或 `http://127.0.0.1:8000/api`）。
2. 不允许默认猜测 `localhost:8000`，也不需要先做端口探测（`netstat`/浏览器试探）。
3. 若未显式传 `--api-base`，脚本会从 `.local-secrets.json` 的 `api_base` 读取；仍缺失则直接报错并要求补配置。

## 工作流

1. 获取当天日期（默认 `Asia/Shanghai` 当天）。
2. 拉取可选项目列表：`GET /api/v1/daily-reports/my-projects`。
3. 解析用户输入为条目：`项目名/进展/工时/风险问题`。
4. 项目映射：
- 匹配到项目：写入该项目。
- 未匹配到项目：归入一条 `学习或其他`（`project_id = null`，`project_name = "学习或其他"`）。
5. 执行强校验（不满足即拒绝提交并提示用户补充）：
- 任一条目中，`progress_content` 与 `work_hours` 必须同时有值。
- 只填了进展没填工时：拒绝。
- 只填了工时没填进展：拒绝。
- 全部条目工时合计必须 `>= 8` 小时。
6. 构造批量提交 payload，调用 `POST /api/v1/daily-reports/batch`。
7. 返回提交结果；失败时给出可执行修复建议（例如哪些条目缺工时/缺进展、总工时差多少）。

## 数据构造规则

1. `report_date` 默认当天（`YYYY-MM-DD`），允许用户显式指定且不得晚于今天。
2. `reports` 仅包含“有内容条目”：
- `work_hours > 0` 或 `progress_content` 非空。
3. `work_hours`：
- 数值范围 `0-24`，建议按 `0.5` 步进。
- 未提供时按 `0` 处理，但如果有进展则必须要求用户补工时。
4. `project_name`：
- 正常项目条目不传。
- 仅当 `project_id = null` 时传 `"学习或其他"`。
5. `push_to` 可选，默认 `[]`。

## 提交前校验清单（必须全通过）

1. 至少有 1 条可提交日报。
2. 每条日报满足：
- `progress_content` 非空 且 `work_hours > 0`。
3. `sum(work_hours) >= 8`。
4. 对“未知项目”进行合并归档到“学习或其他”，避免多条空项目名记录。

## 失败处理策略

1. 如果返回“已提交过该日期日报”：
- 提示用户该日期不可重复提交，建议改日期或改为查看/更新流程（若系统后续支持）。
2. 如果返回“未配置钉钉UserID或手机号”：
- 明确提示需管理员补齐员工钉钉配置后再提交。
3. 如果返回“不是项目成员”：
- 将对应条目建议转入“学习或其他”或让用户确认项目归属。
4. 对网络或 5xx 错误：
- 原样回显服务端 detail，并保留本次 payload 便于重试。

## 请求示例

```json
{
  "report_date": "2026-04-14",
  "push_to": [],
  "reports": [
    {
      "project_id": 101,
      "work_hours": 6,
      "progress_content": "完成日报自动填报接口梳理与联调",
      "risks_issues": "历史数据口径待确认"
    },
    {
      "project_id": null,
      "project_name": "学习或其他",
      "work_hours": 2,
      "progress_content": "学习并整理 OpenClaw skill 编写规范",
      "risks_issues": ""
    }
  ]
}
```

## 可执行脚本

使用 `scripts/submit_daily_report.py` 直接执行端到端流程：

1. 从 Chrome localStorage 自动尝试提取 JWT token（也可手工 `--token`）。
2. 调用 `GET /api/v1/daily-reports/my-projects` 做项目映射。
3. 执行强校验并构造 `/batch` payload。
4. 调用 `POST /api/v1/daily-reports/batch` 提交。

示例：

```bash
python scripts/submit_daily_report.py \
  --api-base https://your-host/api \
  --entries-file data/today_entries.json \
  --credentials-file .local-secrets.json \
  --report-date 2026-04-14 \
  --project-aliases-file data/project_aliases.json \
  --max-retries 2 \
  --retry-backoff-seconds 1.5 \
  --dry-run
```

去掉 `--dry-run` 即实际提交。

`entries-file` 格式（JSON 数组）：

```json
[
  {
    "project_id": 255,
    "project_name": "镇海区数字治气应用（二期）项目",
    "work_hours": 6,
    "progress_content": "完成日报自动填报接口联调",
    "risks_issues": "无"
  },
  {
    "project_name": "OpenClaw Skill 学习",
    "work_hours": 2,
    "progress_content": "学习 skill 编写规范",
    "risks_issues": ""
  }
]
```

说明：
- 若同时提供 `project_id` 和 `project_name`，脚本优先使用 `project_id`。
- 推荐优先传 `project_id`，可避免中英文引号等字符差异导致的匹配失败。
- 脚本支持“语音简称”智能匹配（如“余姚项目”“慈溪二期”）；若你有固定口语别名，建议维护 alias 文件。
- 脚本默认开启 token 自动刷新：遇到 401 会尝试重新从 Chrome localStorage 取 token 并重试一次。
- 脚本默认会对超时/连接失败/429/5xx 做退避重试（参数：`--max-retries`、`--retry-backoff-seconds`）。
- `origin-hint` 默认自动使用 `--api-base` 的域名，不传也可以；只有跨域场景再手工指定。
- 可选 `--expected-user` 用于避免多账号时误提（校验 JWT 中的 `username/sub`）。
- 若 OpenClaw 浏览器没有登录态，可配置 `--login-username` + `--password-env` 走 `/v1/auth/login` 兜底换 token。
- 推荐使用本地私密文件 `.local-secrets.json`（脚本会自动读取，或用 `--credentials-file` 指定），示例：

```json
{
  "api_base": "https://your-host/api",
  "login_username": "你的账号",
  "password": "你的密码",
  "expected_user": "你的账号",
  "password_env": "OPENCLAW_DAILY_REPORT_PASSWORD"
}
```

- 若使用环境变量模式，不要把密码写进命令行或 skill 文件，建议先在终端设置：`OPENCLAW_DAILY_REPORT_PASSWORD=你的密码`。

`project_aliases.json` 示例：

```json
{
  "慈溪二期": 255,
  "余姚项目": "余姚生态环境综合监管平台（余姚二期）"
}
```

## 输出规范

1. 成功时返回：
- 提交日期、总工时、条目数、各项目工时摘要。
2. 失败时返回：
- 失败原因（可读中文）+ 具体修复动作（补哪条工时/进展、还差几小时）。
3. 永远不要在校验失败时发起提交请求。

## 参考

- 接口细节见 `references/api-contract.md`。
- 可执行实现见 `scripts/submit_daily_report.py`。
