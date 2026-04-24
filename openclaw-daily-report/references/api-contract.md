# 日报 API 合同（managementsystem-main）

## Base

- 前缀：`/api/v1`
- 鉴权：`Authorization: Bearer <token>`

## 1) 获取可填报项目

- `GET /daily-reports/my-projects`
- 用途：获取“新增日报”可选项目（不含“学习或其他”这一固定虚拟项）
- 返回关键字段：
  - `id`
  - `project_name`
  - `project_status`
  - `project_manager`

## 2) 批量提交日报（核心）

- `POST /daily-reports/batch`
- 请求体：

```json
{
  "report_date": "YYYY-MM-DD",
  "push_to": ["可选：员工姓名"],
  "reports": [
    {
      "project_id": 123,
      "work_hours": 2.5,
      "progress_content": "今日进展",
      "risks_issues": "风险及问题"
    },
    {
      "project_id": null,
      "project_name": "学习或其他",
      "work_hours": 1.5,
      "progress_content": "非项目类工作",
      "risks_issues": ""
    }
  ]
}
```

- 说明：
  - `project_id = null` 表示“学习或其他”。
  - 后端允许 `progress_content` 为空（由客户端做强校验更稳）。
  - 后端会过滤“工时=0且进展空”的条目。

## 3) 查询日报列表（用于提交后核验，可选）

- `GET /daily-reports`
- 常用参数：
  - `start_date`
  - `end_date`
  - `page`
  - `page_size`
  - `employee_name`

## 常见错误语义

- `400` + `您已经提交过该日期的日报`：重复提交。
- `400` + `无法提交日报：您的账号未配置钉钉UserID或手机号`：人员基础信息缺失。
- `403` + `您不是该项目的成员`：成员权限不足。
- `404` + `项目不存在`：项目 ID 无效或已删除。

## 建议的客户端强校验（Skill 侧）

1. 每条记录必须“工时+进展”同时填写。
2. 总工时必须 `>= 8`。
3. 未匹配项目统一归入 `project_id=null, project_name=学习或其他`。

## 可执行脚本落地

- 脚本：`scripts/submit_daily_report.py`
- 依赖：`requests`
- 能力：
  - `api_base` 必填（`--api-base` 或 `.local-secrets.json` 的 `api_base`）
  - 不再默认猜测 `localhost:8000`，避免误探测错误环境
  - 自动尝试从 Chrome localStorage leveldb 扫描 JWT
  - 候选 token 会按 JWT `exp` 过期时间优先排序（优先选未过期 token）
  - 支持 `--expected-user` 校验 token 身份（防止多账号误提交）
  - 支持 `--credentials-file`（或自动读取技能目录下 `.local-secrets.json`）加载登录账号/密码
  - 当 Chrome 无登录态时，可用 `--login-username` + `--password-env` 调 `/v1/auth/login` 获取 token
  - 调 `my-projects` 做项目名映射
  - 支持 entries 显式传 `project_id`（优先于项目名）
  - 项目名匹配会做标准化（中英文引号/全角差异）
  - 支持语音简称智能匹配（包含简化名、包含关系、模糊匹配）
  - 支持 `--project-aliases-file` 维护你的口语别名
  - 遇到 401 自动刷新 token（默认开启，可用 `--no-auto-token-refresh` 关闭）
  - 对超时/连接失败/429/5xx 自动重试（`--max-retries`、`--retry-backoff-seconds`）
  - `origin-hint` 不传时默认取 `--api-base` 的 host 作为 token 扫描提示
  - 自动归并未知项目到“学习或其他”
  - 先校验后提交到 `/daily-reports/batch`

## 后端行为说明（已优化）

- 批量提交接口现在采用“日报提交优先”策略：
  - 即使钉钉身份未就绪，也不会阻断日报入库。
  - 返回体 `dingtalk_push.identity_ready` 表示钉钉身份是否在提交时已准备好。
