# Output Schema

## Core outputs
- `enterprise_profile.csv`: 企业级概览（企业名、评级片段、规模片段、减排片段）
- `organized_outlet.csv`: 有组织排口
- `tank.csv`: 储罐
- `loading.csv`: 装卸设施
- `wastewater_surface.csv`: 废水液面/废水相关设施
- `fugitive_source.csv`: 工艺无组织源
- `issue_action.csv`: 问题与整改
- `reduction_summary.csv`: 减排汇总
- `unknown_table.csv`: 未分类表行
- `qa_issues.csv`: 质检告警
- `run_summary.json`: 本次运行摘要

## Common fields
- `record_type`: 记录类别
- `enterprise_name`: 企业名称
- `source_file`: 来源文档文件名
- `table_index`: 文档中的表序号（1-based）
- `row_index`: 表中行号（1-based，含表头原始位置）
- `facility_name_raw`: 原始设施/排口名称
- `facility_code`: 编号（如 DA001）
- `process_stage`: 工段/环节/分类
- `pollutant_category`: 污染物或物料类别
- `monitoring_method`: 在线/监测/收集率等监测信息
- `treatment_process`: 治理工艺或废气去向
- `raw_fields`: 原始整行 JSON（用于回溯）

## Interpretation notes
- `facility_code` 在部分类型天然为空（例如无组织源、问题整改）
- `unknown_table.csv` 非错误，表示保留待补规则的数据
- 以 `raw_fields` 为最终兜底真值来源
