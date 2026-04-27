---
name: outlet-structured-extractor
description: 从企业排口总结材料（.docx）批量抽取有组织排口、储罐、装卸、废水液面、无组织源、问题整改等结构化记录并输出 CSV/JSON 与质检摘要。用于处理类似“排口总结材料0306-含炼化”这类批量文档，或需要快速评估字段完整性、缺失热点、未分类表格时。
---

# 排口结构化抽取 Skill

## 目标
将批量企业总结材料 `.docx` 转为可复用结构化数据，并输出可追溯的质检结果。

## 固定流程
1. 先小样本试跑，确认字段映射和分类正常。
2. 再做全量抽取，输出标准 CSV 与 `run_summary.json`。
3. 运行完整性质检，定位缺失热点和未分类表。
4. 对异常文件做定向补规则，不直接手工改结构化结果。

## 脚本
- `scripts/extract_outlet_structured.py`: 主抽取脚本。
- `scripts/assess_structured_quality.py`: 完整性体检脚本。

## 快速命令
```bash
# 1) 试跑（前 5 份）
python3 /Volumes/a盘/project/personal-skills/outlet-structured-extractor/scripts/extract_outlet_structured.py \
  --input-dir "/Volumes/a盘/project/排口总结材料0306-含炼化(1)" \
  --output-dir "/tmp/outlet_trial" \
  --limit 5

# 2) 全量跑
python3 /Volumes/a盘/project/personal-skills/outlet-structured-extractor/scripts/extract_outlet_structured.py \
  --input-dir "/Volumes/a盘/project/排口总结材料0306-含炼化(1)" \
  --output-dir "/tmp/outlet_full" \
  --all

# 3) 质检评估
python3 /Volumes/a盘/project/personal-skills/outlet-structured-extractor/scripts/assess_structured_quality.py \
  --input-dir "/tmp/outlet_full" \
  --write-json "/tmp/outlet_full/quality_report.json"
```

## 抽取规则
1. 优先抽附表，正文仅补企业概述和缺项。
2. 保留 `raw_fields` 原始行文本，确保后续可回溯。
3. 每行记录写入 `source_file + table_index + row_index`。
4. 二级表头默认跳过，避免误入数据行。
5. 无法识别的表行进入 `unknown_table.csv`，不丢弃。

## 质量门槛
1. `enterprise_profile.csv` 必须覆盖全部输入文件。
2. `unknown_table.csv` 占比建议低于 1%。
3. `qa_issues.csv` 仅允许告警，不允许读文件失败类错误。
4. 如果某类关键字段缺失率过高，优先补分类/字段映射规则。

## 输出说明
读取 [references/output-schema.md](references/output-schema.md) 获取各输出文件含义与核心字段。

## 依赖
- Python 3.10+
- `openpyxl` (生成Excel汇总)
- `python-docx`

如未安装：
```bash
pip3 install python-docx openpyxl
```