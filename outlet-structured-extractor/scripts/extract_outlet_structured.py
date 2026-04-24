#!/usr/bin/env python
"""Extract structured emission/facility data from enterprise .docx summary materials.

Trial usage:
    python scripts/extract_outlet_structured.py --limit 5

By default the script attempts to locate the source directory automatically under D:\project.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from docx import Document


TYPE_ORDER = [
    "organized_outlet",
    "tank",
    "loading",
    "wastewater_surface",
    "fugitive_source",
    "issue_action",
    "reduction_summary",
    "unknown_table",
]


@dataclass
class ParseIssue:
    level: str
    code: str
    enterprise_name: str
    source_file: str
    message: str

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "enterprise_name": self.enterprise_name,
            "source_file": self.source_file,
            "message": self.message,
        }


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\u3000", " ")).strip()


def natural_key(path: Path):
    m = re.match(r"^(\d+)", path.name)
    if m:
        return (0, int(m.group(1)), path.name)
    return (1, 999999, path.name)


def detect_input_dir(given: str | None) -> Path:
    if given:
        p = Path(given)
        if p.exists() and p.is_dir():
            return p
        raise FileNotFoundError(f"输入目录不存在: {given}")

    candidates = [
        Path(r"D:\project\排口总结材料0306-含炼化(1)"),
        Path(r"D:\project\排口总结材料0306-含炼化"),
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c

    for p in Path(r"D:\project").glob("*0306*"):
        if p.is_dir():
            return p

    raise FileNotFoundError("未自动发现输入目录，请使用 --input-dir 指定")


def extract_paragraphs(doc: Document) -> list[str]:
    return [normalize_text(p.text) for p in doc.paragraphs if normalize_text(p.text)]


def extract_profile(paragraphs: list[str], source_file: str) -> dict:
    enterprise_name = paragraphs[0] if paragraphs else ""
    rating = ""
    products_scale = ""
    reduction_text = ""

    for text in paragraphs:
        if not rating and "绩效评级" in text:
            rating = text
        if not products_scale and ("产品" in text and "生产规模" in text):
            products_scale = text
        if not reduction_text and ("减排空间" in text or "减排量" in text):
            reduction_text = text

    return {
        "enterprise_name": enterprise_name,
        "source_file": source_file,
        "rating_excerpt": rating,
        "products_scale_excerpt": products_scale,
        "reduction_excerpt": reduction_text,
    }


def make_unique_headers(headers: list[str]) -> list[str]:
    result = []
    seen: dict[str, int] = defaultdict(int)
    for idx, raw in enumerate(headers, start=1):
        key = normalize_text(raw) or f"col_{idx}"
        seen[key] += 1
        if seen[key] > 1:
            key = f"{key}__{seen[key]}"
        result.append(key)
    return result


def classify_table(headers: list[str]) -> str:
    h = "|".join(headers)

    if "问题内容描述" in h and ("建议措施" in h or "企业已采取措施" in h):
        return "issue_action"
    if "无组织废气名称" in h:
        return "fugitive_source"
    if (
        ("排放源名称" in h and "所在位置" in h)
        or ("废水" in h and "液面" in h)
        or ("装置名称" in h and "设施名称" in h and "涉VOCs" in h)
    ):
        return "wastewater_surface"
    if "装卸" in h and ("周转量" in h or "装载" in h or "装卸量" in h):
        return "loading"
    if "储罐" in h and ("周转量" in h or "容积" in h or "罐型" in h):
        return "tank"
    if (
        "有组织排放口名称" in h
        or ("排放口名称" in h and "检测因子" in h)
        or ("排气筒名称" in h and "污染物" in h)
        or ("排放口编号" in h and "主要污染物名称" in h)
        or ("排放口编号" in h and "检测因子" in h)
    ):
        return "organized_outlet"
    if "源项" in h and "整改建议" in h and "减排" in h:
        return "reduction_summary"
    return "unknown_table"


def is_repeat_header(row: list[str], headers: list[str]) -> bool:
    joined = "|".join(row)
    if not joined.strip():
        return True
    if row and row[0] == "序号":
        return True
    if "序号" in joined and "排放口" in joined:
        return True
    overlap = sum(1 for value in row if value and value in headers)
    return overlap >= max(2, len([x for x in row if x]) - 1)


def pick_value(row: dict[str, str], *needles: str) -> str:
    for key, value in row.items():
        for needle in needles:
            if needle in key and normalize_text(value):
                return normalize_text(value)
    return ""


def normalize_row(
    row: dict[str, str],
    record_type: str,
    enterprise_name: str,
    source_file: str,
    table_index: int,
    row_index: int,
) -> dict:
    base = {
        "record_type": record_type,
        "enterprise_name": enterprise_name,
        "source_file": source_file,
        "table_index": table_index,
        "row_index": row_index,
    }

    if record_type == "organized_outlet":
        base.update(
            {
                "facility_name_raw": pick_value(row, "有组织排放口名称", "排放口名称", "排气筒名称"),
                "facility_code": pick_value(row, "排放口编号"),
                "facility_type": "organized_outlet",
                "process_stage": pick_value(row, "排放性质", "排气筒分类"),
                "pollutant_category": pick_value(row, "主要污染物名称", "检测因子", "污染物种类"),
                "monitoring_method": pick_value(row, "是否设置在线", "是否设置在线监测设施"),
                "treatment_process": pick_value(row, "废气处理工艺"),
                "dcs_connected": pick_value(row, "DCS"),
                "source_section": "附表-有组织排放口",
            }
        )
    elif record_type == "tank":
        base.update(
            {
                "facility_name_raw": pick_value(row, "储罐名称", "储罐位号", "位号"),
                "facility_code": pick_value(row, "储罐位号"),
                "facility_type": "tank",
                "process_stage": pick_value(row, "所属区块", "类别"),
                "pollutant_category": pick_value(row, "物料名称", "储存物料"),
                "monitoring_method": pick_value(row, "是否设有氮封"),
                "treatment_process": pick_value(row, "是否有治理设施", "边缘密封方式"),
                "source_section": "附表-储罐",
            }
        )
    elif record_type == "loading":
        base.update(
            {
                "facility_name_raw": pick_value(row, "装卸设施名称", "装卸名称"),
                "facility_code": pick_value(row, "装卸设施位号"),
                "facility_type": "loading",
                "process_stage": pick_value(row, "装卸地块", "运输工具", "装载方式"),
                "pollutant_category": pick_value(row, "物料名称"),
                "monitoring_method": pick_value(row, "装卸泵信号是否接入DCS"),
                "treatment_process": pick_value(row, "挥发性有机物处理工艺", "废气去向"),
                "source_section": "附表-装卸设施",
            }
        )
    elif record_type == "wastewater_surface":
        base.update(
            {
                "facility_name_raw": pick_value(row, "设施名称", "排放源名称"),
                "facility_code": "",
                "facility_type": "wastewater_surface",
                "process_stage": pick_value(row, "环节", "所在位置", "装置名称"),
                "pollutant_category": pick_value(row, "涉VOCs名称", "涉异味物质名称", "是否有明显异味"),
                "monitoring_method": pick_value(row, "VOCs检测浓度", "是否有明显异味"),
                "treatment_process": pick_value(row, "是否加盖密闭", "废气是否收集处理", "输送方式"),
                "source_section": "附表-废水液面",
            }
        )
    elif record_type == "fugitive_source":
        base.update(
            {
                "facility_name_raw": pick_value(row, "无组织废气名称", "废气产生点位"),
                "facility_code": "",
                "facility_type": "fugitive_source",
                "process_stage": pick_value(row, "工段或工艺名称"),
                "pollutant_category": "VOCs/异味",
                "monitoring_method": pick_value(row, "预计收集率"),
                "treatment_process": pick_value(row, "废气收集方式", "废气去向"),
                "source_section": "附表-工艺无组织",
            }
        )
    elif record_type == "issue_action":
        base.update(
            {
                "facility_name_raw": pick_value(row, "问题类型"),
                "facility_code": "",
                "facility_type": "issue_action",
                "process_stage": pick_value(row, "问题分类"),
                "pollutant_category": "",
                "monitoring_method": pick_value(row, "完成情况", "企业已采取措施"),
                "treatment_process": pick_value(row, "建议措施"),
                "source_section": "附表-问题整改",
            }
        )
    elif record_type == "reduction_summary":
        base.update(
            {
                "facility_name_raw": pick_value(row, "源项"),
                "facility_code": "",
                "facility_type": "reduction_summary",
                "process_stage": pick_value(row, "问题点"),
                "pollutant_category": pick_value(row, "减排量", "NOx减排量"),
                "monitoring_method": "",
                "treatment_process": pick_value(row, "整改建议"),
                "source_section": "附表-减排汇总",
            }
        )
    else:
        base.update(
            {
                "facility_name_raw": "",
                "facility_code": "",
                "facility_type": "unknown_table",
                "process_stage": "",
                "pollutant_category": "",
                "monitoring_method": "",
                "treatment_process": "",
                "source_section": "附表-未分类",
            }
        )

    base["raw_fields"] = json.dumps(row, ensure_ascii=False)
    return base


def iter_rows(table) -> tuple[list[str], Iterable[tuple[int, dict[str, str]]]]:
    matrix: list[list[str]] = []
    for raw_row in table.rows:
        matrix.append([normalize_text(cell.text) for cell in raw_row.cells])

    matrix = [row for row in matrix if any(x for x in row)]
    if not matrix:
        return [], []

    headers = make_unique_headers(matrix[0])

    def _rows():
        for idx, raw_values in enumerate(matrix[1:], start=2):
            if is_repeat_header(raw_values, headers):
                continue
            if not any(raw_values):
                continue
            row_map = {headers[col]: raw_values[col] if col < len(raw_values) else "" for col in range(len(headers))}
            yield idx, row_map

    return headers, _rows()


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    keys = []
    for row in rows:
        for k in row.keys():
            if k not in keys:
                keys.append(k)

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract structured outlet/facility data from docx summaries")
    parser.add_argument("--input-dir", help="Source directory containing .docx files")
    parser.add_argument("--output-dir", default="data/outlet_structured_trial", help="Output directory")
    parser.add_argument("--limit", type=int, default=5, help="Process first N files by natural order")
    parser.add_argument("--all", action="store_true", help="Process all files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_dir = detect_input_dir(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*.docx"), key=natural_key)
    if not args.all:
        files = files[: max(0, args.limit)]

    if not files:
        print("未找到 .docx 文件")
        return 1

    records_by_type: dict[str, list[dict]] = {k: [] for k in TYPE_ORDER}
    enterprise_profiles: list[dict] = []
    issues: list[ParseIssue] = []

    for file_path in files:
        try:
            doc = Document(file_path)
        except Exception as exc:
            issues.append(
                ParseIssue(
                    level="error",
                    code="docx_read_failed",
                    enterprise_name="",
                    source_file=file_path.name,
                    message=str(exc),
                )
            )
            continue

        paragraphs = extract_paragraphs(doc)
        profile = extract_profile(paragraphs, file_path.name)
        enterprise_profiles.append(profile)
        enterprise_name = profile["enterprise_name"]

        if not enterprise_name:
            issues.append(
                ParseIssue(
                    level="error",
                    code="missing_enterprise_name",
                    enterprise_name="",
                    source_file=file_path.name,
                    message="首段未识别到企业名称",
                )
            )

        if len(doc.tables) == 0:
            issues.append(
                ParseIssue(
                    level="warn",
                    code="no_tables",
                    enterprise_name=enterprise_name,
                    source_file=file_path.name,
                    message="文档无附表，需依赖正文补录",
                )
            )

        outlet_code_name_map: dict[str, set[str]] = defaultdict(set)

        for table_index, table in enumerate(doc.tables, start=1):
            headers, rows_iter = iter_rows(table)
            if not headers:
                continue
            record_type = classify_table(headers)

            row_count = 0
            for row_index, row in rows_iter:
                row_count += 1
                normalized = normalize_row(
                    row,
                    record_type,
                    enterprise_name,
                    file_path.name,
                    table_index,
                    row_index,
                )
                records_by_type[record_type].append(normalized)

                if record_type == "organized_outlet":
                    facility_name = normalized.get("facility_name_raw", "")
                    facility_code = normalized.get("facility_code", "")
                    if not facility_name and not facility_code:
                        issues.append(
                            ParseIssue(
                                level="warn",
                                code="organized_missing_name",
                                enterprise_name=enterprise_name,
                                source_file=file_path.name,
                                message=f"表{table_index} 第{row_index}行缺少排口名称",
                            )
                        )
                    if facility_code:
                        outlet_code_name_map[facility_code].add(facility_name or "(空名称)")

            if row_count == 0:
                issues.append(
                    ParseIssue(
                        level="warn",
                        code="empty_table_rows",
                        enterprise_name=enterprise_name,
                        source_file=file_path.name,
                        message=f"表{table_index} 提取后无有效数据行",
                    )
                )

        for code, name_set in outlet_code_name_map.items():
            if len(name_set) > 1:
                issues.append(
                    ParseIssue(
                        level="warn",
                        code="outlet_code_multi_name",
                        enterprise_name=enterprise_name,
                        source_file=file_path.name,
                        message=f"排口编号 {code} 对应多个名称: {', '.join(sorted(name_set))}",
                    )
                )

    write_csv(output_dir / "enterprise_profile.csv", enterprise_profiles)
    for record_type in TYPE_ORDER:
        write_csv(output_dir / f"{record_type}.csv", records_by_type[record_type])
    write_csv(output_dir / "qa_issues.csv", [x.as_dict() for x in issues])

    summary = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir.resolve()),
        "processed_files": [f.name for f in files],
        "processed_file_count": len(files),
        "record_counts": {k: len(v) for k, v in records_by_type.items()},
        "issue_counts": dict(Counter(x.code for x in issues)),
    }

    with (output_dir / "run_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
