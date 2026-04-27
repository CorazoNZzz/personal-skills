# API Review - openclaw-daily-report

> 生成时间：2026-04-24
> 参考文档：`references/api-contract.md`
> 对照脚本：`scripts/submit_daily_report.py`

---

## 一、接口清单（来自 API_CONTRACT.md）

| # | 用途 | 方法 | URL | 认证 | 关键参数 |
|---|------|------|-----|------|---------|
| 1 | 获取可填报项目 | GET | `/api/v1/daily-reports/my-projects` | Bearer Token | 无 |
| 2 | 批量提交日报（核心） | POST | `/api/v1/daily-reports/batch` | Bearer Token | report_date, push_to, reports[] |
| 3 | 查询日报列表 | GET | `/api/v1/daily-reports` | Bearer Token | start_date, end_date, page, page_size, employee_name |
| — | 登录获取 Token | POST | `/v1/auth/login` | 无 | username, password |

---

## 二、每个接口的实现现状

### 接口 1：`GET /api/v1/daily-reports/my-projects`

**合同要求：** `GET /api/v1/daily-reports/my-projects`

**实际实现（`submit_daily_report.py` L452）：**
```python
url = f"{api_base.rstrip('/')}/v1/daily-reports/my-projects"
```

**状态：❌ 路径不匹配**

- 合同：`/api/v1/daily-reports/my-projects`
- 实际：`{api_base}/v1/daily-reports/my-projects`（缺少 `/api` 前缀）

如果 `api_base` 传入的是 `https://example.com/api`（含 `/api`），则实际 URL 会变成 `/api/v1/...`，恰好对齐。但合同明确写明 `/api/v1` 是固定前缀，若 `api_base` 不含 `/api` 则路径会缺少一级。

---

### 接口 2：`POST /api/v1/daily-reports/batch`

**合同要求：** `POST /api/v1/daily-reports/batch`

**实际实现（`submit_daily_report.py` L510）：**
```python
url = f"{api_base.rstrip('/')}/v1/daily-reports/batch"
```

**状态：❌ 路径不匹配（同接口1）**

同上，缺少固定 `/api` 前缀的保证机制。

---

### 接口 3：`GET /api/v1/daily-reports`（查询列表）

**合同要求：** `GET /api/v1/daily-reports`

**实际实现：** `submit_daily_report.py` 中**未实现**此接口。

**状态：⚠️ 未实现**（属于可选功能，API_CONTRACT 标注为"可选"，风险低）

---

### 登录接口：`POST /v1/auth/login`

**合同要求：** `/v1/auth/login`

**实际实现（`submit_daily_report.py` L385）：**
```python
url = f"{api_base.rstrip('/')}/v1/auth/login"
```

**状态：✅ 路径一致**（`/v1/auth/login` 不含 `/api` 前缀，与合同一致）

---

## 三、参数一致性检查

### `/daily-reports/batch` 请求体

| 字段 | 合同要求 | 脚本实现 | 状态 |
|------|---------|---------|------|
| report_date | string (YYYY-MM-DD) | ✅ `report_date` | ✅ |
| push_to | string[] | ✅ `push_to` | ✅ |
| reports[].project_id | int \| null | ✅ `int \| null` | ✅ |
| reports[].project_name | string (学习或其他) | ✅ `project_name` | ✅ |
| reports[].work_hours | float | ✅ `float` | ✅ |
| reports[].progress_content | string | ✅ | ✅ |
| reports[].risks_issues | string | ✅ | ✅ |

客户端强校验（工时+进展同时填写、总工时>=8）：**✅ 已实现**

---

## 四、遗留问题列表

| 优先级 | 问题 | 说明 |
|--------|------|------|
| 🔴 高 | `/api/v1` 前缀不一致 | 合同规定所有日报接口前缀为 `/api/v1`，但脚本拼接路径时用的是 `/v1`，如果 `api_base` 不包含 `/api` 会导致 404。建议：始终在拼接日报接口 URL 时显式加上 `/api` 前缀，或在文档中明确 `api_base` 必须以 `/api` 结尾。 |
| 🟡 中 | 查询列表接口未实现 | `/api/v1/daily-reports`（GET）脚本中未实现，仅在合同中标注"可选"，不影响提交核心功能。 |
| 🟢 低 | Token 来源依赖 Chrome | 脚本默认从 Chrome localStorage LevelDB 扫描 token，Mac 上 Chrome 数据在 `~/Library/Application Support/Google/Chrome/`，但 LevelDB 路径依赖 `LOCALAPPDATA`（Windows 环境变量），Mac 上该变量为空，会导致 `iter_chrome_leveldb_files` 返回空列表，token 扫描失效。**仅影响 Mac 上的无参调用**（有 token 参数或 login 参数则不受影响）。 |

---

## 五、修复建议

### 1. 修复 `/api/v1` 前缀问题（高优先级）

在拼接所有日报相关接口 URL 时，始终确保包含 `/api` 前缀。参考修复：

```python
def _daily_reports_url(api_base: str, path: str) -> str:
    """Build /api/v1/daily-reports/* URL, ensuring /api prefix."""
    base = api_base.rstrip("/")
    if not base.endswith("/api"):
        base = base + "/api"
    return f"{base}/v1/daily-reports{path}"
```

### 2. 修复 Mac Chrome LevelDB 路径（低优先级）

`iter_chrome_leveldb_files()` 依赖 Windows 环境变量 `LOCALAPPDATA`，Mac 上应使用：
```python
# Mac
leveldb = Path.home() / "Library/Application Support/Google/Chrome/User Data/{profile}/Local Storage/leveldb"
```

### 3. 补充查询列表接口（如需核验功能）

可选实现 `GET /api/v1/daily-reports?start_date=&end_date=&page=&page_size=`。

---

*Review by: OpenClaw subagent | 2026-04-24*
