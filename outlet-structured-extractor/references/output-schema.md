# Output Schema

## Core outputs
- `document_section.csv`: 全文标题展开表，按 docx 原始顺序列出每一个独立标题及标题下面的直接内容、完整章节内容、子标题和关联表格
- `enterprise_profile.csv`: 企业级概览（企业名、生产简介、问题和减排空间、重点异味点、评级片段、规模片段、减排片段）
- `section_summary.csv`: 正文分项分析汇总，按 docx 序列记录排气筒、储罐、装卸、废水液面、工艺过程无组织、开停工检维修、数字化、整改建议等章节
- `outlet_overview.csv`: 排气筒概况专表，摘录排口/排气筒总数、高架排气筒（50米及以上）数量、排口类型/构成说明、DCS 状态、问题识别、减排空间识别
- `issue_identification.csv`: 正文“问题识别”逐条记录
- `reduction_space_identification.csv`: 正文“减排空间识别”逐条记录
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
- `outlet_structured_summary.xlsx`: 按 docx 正文逻辑排序的 Excel 汇总，各 sheet 与上述 CSV 对应

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
- `raw_fields`: 原始整行或原始段落文本（用于回溯）

## Narrative fields
- `heading_order`: 标题在 docx 全文中的顺序
- `heading_level`: 标题层级，优先来自 Word 标题样式；普通样式中的短编号/冒号标题按启发式补充
- `heading_text`: 标题文本
- `heading_style`: Word 段落样式名称
- `heading_detection`: 标题识别来源，如 `style_heading`、`style_title`、`numbered_heading`
- `parent_path`: 从文档标题到当前标题的层级路径
- `direct_content`: 当前标题到下一个任意标题之间的直接内容
- `section_content`: 当前标题到下一个同级或上级标题之间的完整内容，包含子标题及子标题内容
- `child_headings`: 当前标题范围内的子标题列表
- `direct_table_refs`: `direct_content` 范围内关联的表格编号
- `section_table_refs`: `section_content` 范围内关联的表格编号
- `production_intro`: 企业生产简介，包括行业、评级、主要产品、生产规模、生产工艺流程等正文描述
- `problems_and_reduction_space`: 企业层面的“问题和减排空间”段落
- `key_odor_points`: 企业层面的“重点异味点”段落
- `section_order`: 分项章节在 docx 正文中的顺序
- `section_name`: 分项章节名称
- `overview_heading`: 概况类小节标题，如“排气筒概况”“储罐分类统计”
- `overview_text`: 概况正文
- `issue_identification`: 当前分项的“问题识别”合并段落
- `reduction_space_identification`: 当前分项的“减排空间识别”合并段落
- `item_order`: 问题或减排空间在当前分项下的序号
- `item_text`: 拆分后的单条问题或单条减排空间

## Outlet overview fields
- `total_outlet_count`: 排口/排气筒总数
- `elevated_stack_50m_plus_count`: 高架排气筒（50米及以上）数量
- `outlet_composition_text`: 排口类型/构成说明，例如有机废气（异味）处理装置排气筒数量及括号中的排口说明
- `dcs_status`: DCS 相关状态摘要

## Interpretation notes
- `facility_code` 在部分类型天然为空（例如无组织源、问题整改、正文问题识别）
- `unknown_table.csv` 非错误，表示保留待补规则的数据
- 以 `raw_fields` 为最终兜底真值来源
