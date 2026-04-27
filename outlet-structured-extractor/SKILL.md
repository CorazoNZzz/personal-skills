---
name: outlet-structured-extractor
description: 从企业排口总结材料（.docx）批量抽取全文标题内容、企业概述、排气筒概况、问题识别、减排空间识别及附表明细，并输出按文档顺序组织的 CSV/XLSX/JSON 与质检摘要。用于处理类似“排口总结材料0306-含炼化”这类批量文档，或需要快速评估字段完整性、缺失热点、未分类表格时。
---

# 排口结构化抽取 Skill

## 目标
将批量企业总结材料 `.docx` 转为可复用结构化数据。输出应先把全文每个标题及标题下内容按原始顺序晒出来，再抽重点摘要字段并保留附表明细。

## 固定流程
1. 先小样本试跑，确认字段映射和分类正常。
2. 再做全量抽取，输出标准 CSV、按文档顺序排列的 `outlet_structured_summary.xlsx` 与 `run_summary.json`。
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
1. 全文标题展开是第一输出：`document_section.csv` 必须按 docx 原始顺序列出每一个独立标题，以及该标题下的 `direct_content` 和 `section_content`。
2. 标题识别优先使用 Word 标题样式（Title、Heading 1/2/3、Caption），同时补充普通样式里的短编号标题、冒号标题、附表/附图标题。
3. 父标题不能因为下面有子标题就留空；父标题使用 `section_content` 汇总到下一个同级或上级标题前的全部内容。
4. 表格仍单独结构化；如果某个标题下面接表格，`document_section.csv` 需记录 `direct_table_refs` / `section_table_refs`。
5. 企业概述必须包含 `production_intro`、`problems_and_reduction_space`、`key_odor_points`。
6. 分项分析按 docx 序列抽取为 `section_summary.csv`，重点包括排气筒、储罐、装卸、废水液面、工艺过程无组织、开停工检维修、数字化、整改建议。
7. 排气筒概况单独输出 `outlet_overview.csv`，需摘出排口/排气筒总数、高架排气筒（50米及以上）数量、排口类型/构成说明、DCS 状态、问题识别、减排空间识别。
8. 各分项的“问题识别”逐条输出到 `issue_identification.csv`；“减排空间识别”逐条输出到 `reduction_space_identification.csv`，不要只保留合并段落。
9. 附表仍需保留为明细表：有组织排口、储罐、装卸、废水液面、无组织源、问题整改、减排汇总等。
10. 保留 `raw_fields` 原始行/段落文本，确保后续可回溯。
11. 每行附表记录写入 `source_file + table_index + row_index`。
12. 二级表头默认跳过，避免误入数据行。
13. 无法识别的表行进入 `unknown_table.csv`，不丢弃。

## 质量门槛
1. `enterprise_profile.csv` 必须覆盖全部输入文件。
2. `document_section.csv` 必须覆盖每个输入文件的标题，且标题顺序应与 docx 原文一致。
3. `outlet_overview.csv` 应覆盖包含“排气筒”章节的企业，并尽量解析出总排口数和 50 米及以上高架排气筒数量。
4. `section_summary.csv` 的章节顺序应与 docx 正文一致。
5. `unknown_table.csv` 占比建议低于 1%。
6. `qa_issues.csv` 仅允许告警，不允许读文件失败类错误。
7. 如果某类关键字段缺失率过高，优先补分类/字段映射规则。

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
