---
name: week-report-integrator
description: 将日报归档自动整合成周报内容，并通过 mcporter 写入金山文档表格。用于每周五周报汇总场景，支持按项目名自动定位行号，流程固定为“先预览、确认后写入、追加不覆盖”。
---

# 周报整合 Skill

## 目标
把日报系统数据整合为周报文本，写入金山文档 `瑞蓝科技项目最新进展清单.xlsx` 的 `2026年` sheet。

## 固定上下文
- 文档链接: https://www.kdocs.cn/l/cjzrnv1A40I1
- `file_id`: `bMVCNhm4Q9Mr8yLThHc6rxNE6kiJZ6TE7`
- `drive_id`: `2534342736`
- 目标 sheet: `2026年` (`sheetId=4`)
- 历史 sheet: `2025年` (`sheetId=1`)
- 版本方向: 最新版本在左侧（列号更小）
- 当前最新版本块: `col=5`
- 写入列: 本周工作小结=`col+1`，下周工作计划=`col+2`
- 写入 `opType` 必须是 `formula`

## 数据约束
- 日报系统无“历史日报查询”接口。
- 周报汇总基于本地归档: `data/daily_records.jsonl`
- secrets 来源: `../openclaw-daily-report/.local-secrets.json`
- secrets 读取编码必须用 `utf-8-sig`（兼容 BOM）

## 执行原则
1. 每周五触发。
2. 先确认汇总范围和下周计划，再写入。
3. 默认只预览，不直接写。
4. 追加写入（读旧值->拼接->写回），不覆盖他人内容。

## 行号定位策略
- 优先使用 `--target-row`（手动指定，最高优先级）。
- 未传 `--target-row` 时，使用 `--project-name` 自动定位行：
- 扫描项目名列（默认第 2 列；第 1 列通常是序号）
- 先做规范化精确匹配，再做模糊匹配
- 匹配到 0 行或多行会报错并提示改用 `--target-row`

## 脚本
- `scripts/append_daily_record.py`: 把当天日报追加归档到 `daily_records.jsonl`
- `scripts/sync_weekly_kdocs.py`: 周报整合、预览、确认、写入
- `scripts/mcporter_templates.example.json`: 本机可用的 mcporter 模板（已填实参）
- `scripts/run_weekly_sync.ps1`: 周五一键预览/写入入口

## 每日归档
```powershell
python scripts/append_daily_record.py \
  --report-date 2026-04-17 \
  --entries-file ..\openclaw-daily-report\data\today_entries.json \
  --archive-file data\daily_records.jsonl \
  --replace-date
```

## 周五一键预览（按项目名自动定位，推荐）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_weekly_sync.ps1 \
  -ProjectName 镇海区“数字治气”应用（二期）项目 \
  -ProjectCol 2 \
  -StartDate 2026-04-14 \
  -EndDate 2026-04-18 \
  -NextWeekPlanFile data\next_week_plan.txt
```

## 周五一键写入（按项目名自动定位）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_weekly_sync.ps1 \
  -ProjectName 镇海区“数字治气”应用（二期）项目 \
  -ProjectCol 2 \
  -StartDate 2026-04-14 \
  -EndDate 2026-04-18 \
  -NextWeekPlanFile data\next_week_plan.txt \
  -Apply
```

## 周五一键写入（手动行号兜底）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_weekly_sync.ps1 \
  -TargetRow 4 \
  -StartDate 2026-04-14 \
  -EndDate 2026-04-18 \
  -NextWeekPlanFile data\next_week_plan.txt \
  -Apply
```

## 直接用 sync_weekly_kdocs.py（高级）
- 行号相关:
- `--target-row` 手动指定目标行
- `--project-name` 自动定位目标行
- `--project-col` 项目名列（当前文档默认推荐 2）
- `--scan-row-from`, `--scan-row-to` 自动定位扫描范围
- 其他:
- 可传 `--mcporter-template-file scripts/mcporter_templates.example.json`
- 可传 `--read-cell-cmd-template` / `--write-cell-cmd-template` 覆盖模板
- 行列默认按 1-based 输入，脚本内部自动转 0-based（`--index-base 1`）

## 失败兜底
- 先用 `--backend mock` 验证预览拼接逻辑。
- 写入失败时保留 `data/last_preview.json`，便于复核与重试。
