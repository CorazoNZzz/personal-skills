#!/usr/bin/env python3
"""Extract structured emission/facility data from enterprise .docx summary materials.

Trial usage:
    python scripts/extract_outlet_structured.py --limit 5

Full run:
    python scripts/extract_outlet_structured.py --all
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
    "enterprise_profile",
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
    """Sort: files with leading digit first, numeric ascending."""
    name = path.name
    m = re.match(r"^(\d+)", name)
    if m:
        return (0, int(m.group(1)), name)
    return (1, 999999, name)


def detect_input_dir(given: str | None) -> Path:
    if given:
        p = Path(given)
        if p.exists() and p.is_dir():
            return p
        raise FileNotFoundError(f"输入目录不存在: {given}")

    # Candidate paths — adjust for your environment
    candidates = [
        Path("/Volumes/a盘/project/排口总结材料0306-含炼化(1)"),
        Path("/Volumes/a盘/project/排口总结材料0306-含炼化"),
        Path("D:/project/排口总结材料0306-含炼化(1)"),
        Path("D:/project/排口总结材料0306-含炼化"),
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c

    # Last resort: glob
    for base in [Path("/Volumes/a盘/project"), Path("D:/project")]:
        if base.exists():
            for p in base.glob("*0306*"):
                if p.is_dir():
                    return p

    raise FileNotFoundError(
        "未自动发现输入目录，请使用 --input-dir 参数指定\n"
        "示例: python scripts/extract_outlet_structured.py \\\n"
        "  --input-dir '/Volumes/a盘/project/排口总结材料0306-含炼化(1)' \\\n"
        "  --output-dir data/outlet_structured_trial --limit 5"
    )


def extract_paragraphs(doc: Document) -> list[str]:
    return [normalize_text(p.text) for p in doc.paragraphs if normalize_text(p.text)]


def extract_profile(paragraphs: list[str], source_file: str) -> dict:
    enterprise_name = paragraphs[0] if paragraphs else ""
    rating = ""
    products_scale = ""
    reduction_text = ""

    for text in paragraphs:
        t = text
        if not rating and ("绩效评级" in t or "评定" in t):
            rating = t
        if not products_scale and ("产品" in t and "规模" in t):
            products_scale = t
        if not reduction_text and ("减排空间" in t or "减排量" in t or "减排" in t):
            reduction_text = t

    return {
        "enterprise_name": enterprise_name,
        "source_file": source_file,
        "rating_excerpt": rating,
        "products_scale_excerpt": products_scale,
        "reduction_excerpt": reduction_text,
    }


def make_unique_headers(headers: list[str]) -> list[str]:
    """Append __N suffix when duplicate header names appear."""
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
    """
    Classify table type from its header row.
    Headers are already normalized via make_unique_headers.
    We search in the raw (non-normalized) headers joined string to avoid
    issues with duplicate-header deduplication.
    """
    h = "|".join(headers)

    # ── issue_action ──────────────────────────────────────────────
    # 必有：问题内容描述 + (建议措施 | 企业已采取措施)
    if "问题内容描述" in h:
        if "建议措施" in h or "企业已采取措施" in h:
            return "issue_action"

    # ── reduction_summary ──────────────────────────────────────────
    # 必有：源项 + 整改建议 + 减排量/减排
    if "源项" in h and "整改建议" in h:
        if "减排" in h:
            return "reduction_summary"
        # Fallback: just source items + suggestions (some files omit "减排" in header)
        return "reduction_summary"

    # ── fugitive_source ────────────────────────────────────────────
    if "无组织废气名称" in h:
        return "fugitive_source"

    # ── organized_outlet ───────────────────────────────────────────
    # 有组织排放口名称 / 排气筒名称 + 污染物/检测因子
    if "有组织排放口名称" in h:
        return "organized_outlet"
    if "排气筒名称" in h and "污染物" in h:
        return "organized_outlet"
    if "排气筒名称" in h and "检测因子" in h:
        return "organized_outlet"
    if "排放口编号" in h and "主要污染物名称" in h:
        return "organized_outlet"
    if "排放口编号" in h and "检测因子" in h:
        return "organized_outlet"

    # ── tank ───────────────────────────────────────────────────────
    # 储罐名称（含储罐位号）/ 罐型 + 周转量/容积
    if "储罐" in h and "罐型" in h:
        return "tank"
    if "储罐" in h and "周转量" in h:
        return "tank"

    # ── loading ────────────────────────────────────────────────────
    # 装卸设施名称 + (周转量 | 装载量 | 装卸量)
    if "装卸设施名称" in h or "装卸" in h:
        if "周转量" in h or "装载量" in h or "装卸量" in h:
            return "loading"
        if "装卸方式" in h:
            return "loading"

    # ── wastewater_surface ─────────────────────────────────────────
    # 废水液面 / 排放源名称(含"液面"/"敞开") / 装置名称+设施名称+涉VOCs
    if "废水" in h and "液面" in h:
        return "wastewater_surface"
    if "排放源名称" in h and "所在位置" in h:
        return "wastewater_surface"
    if "排放源名称" in h and "是否加盖" in h:
        return "wastewater_surface"
    if "装置名称" in h and "设施名称" in h and "涉VOCs" in h:
        return "wastewater_surface"

    return "unknown_table"



def is_repeat_header(row: list[str], headers: list[str]) -> bool:
    """Detect sub-header / year-split rows that duplicate the header content."""
    row_text = normalize_text(" ".join(row))
    header_text = normalize_text(" ".join(headers))
    if not row_text or not header_text:
        return False
    header_words = set(w for w in re.split(r"[\s|,，、]+", header_text) if len(w) > 1)
    if not header_words:
        return False
    match_count = sum(1 for w in header_words if w in row_text)
    return match_count / len(header_words) >= 0.7


def parse_table(
    table, source_file: str, table_index: int, enterprise_name: str
) -> tuple[str, list[dict]]:
    """Extract rows from a docx table, classify type, return (type, rows)."""
    raw_rows: list[list[str]] = []
    for row in table.rows:
        cells = [normalize_text(cell.text) for cell in row.cells]
        deduped = []
        prev = None
        for c in cells:
            if c != prev:
                deduped.append(c)
            prev = c
        raw_rows.append(deduped)

    if len(raw_rows) < 2:
        return ("unknown_table", [])

    header_row = raw_rows[0]
    if all(c == "" for c in header_row) and len(raw_rows) > 2:
        header_row = raw_rows[1]
        data_rows = raw_rows[2:]
    else:
        data_rows = raw_rows[1:]

    headers = make_unique_headers(header_row)
    table_type = classify_table(header_row)

    records = []
    for ri, raw in enumerate(data_rows):
        if not any(c.strip() for c in raw):
            continue
        if is_repeat_header(raw, header_row):
            continue

        row_dict = {"source_file": source_file, "table_index": table_index, "row_index": ri}
        for ci, h in enumerate(headers):
            val = raw[ci].strip() if ci < len(raw) else ""
            row_dict[h] = val
        row_dict["enterprise_name"] = enterprise_name
        row_dict["record_type"] = table_type
        row_dict["raw_fields"] = "|".join(raw)
        records.append(row_dict)

    return (table_type, records)


def process_file(docx_path: Path, issues: list[ParseIssue]) -> dict:
    """Process one .docx file and return structured records by type."""
    source_file = docx_path.name
    result: dict[str, list[dict]] = defaultdict(list)

    try:
        doc = Document(str(docx_path))
    except Exception as e:
        issues.append(ParseIssue("ERROR", "DOCX_OPEN", "", source_file, str(e)))
        return result

    paragraphs = extract_paragraphs(doc)
    enterprise_name = paragraphs[0] if paragraphs else source_file
    profile = extract_profile(paragraphs, source_file)
    result["enterprise_profile"].append(profile)

    for ti, table in enumerate(doc.tables):
        table_type, rows = parse_table(table, source_file, ti, enterprise_name)
        result[table_type].extend(rows)
        if table_type == "unknown_table" and rows:
            issues.append(
                ParseIssue(
                    "WARN",
                    "UNKNOWN_TABLE",
                    enterprise_name,
                    source_file,
                    f"Table {ti}: {rows[0].get('raw_fields', '')[:120]}",
                )
            )

    return result


def write_csvs(all_records: dict[str, list[dict]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for table_type in TYPE_ORDER:
        rows = all_records.get(table_type, [])
        csv_path = output_dir / f"{table_type}.csv"
        if not rows:
            csv_path.write_text("", encoding="utf-8-sig")
            continue

        field_set: set[str] = set()
        for r in rows:
            field_set.update(r.keys())
        standard = ["source_file", "table_index", "row_index", "enterprise_name", "record_type", "raw_fields"]
        remaining = [f for f in field_set if f not in standard]
        seen = set()
        final_fields = []
        for f in standard + remaining:
            if f not in seen:
                seen.add(f)
                final_fields.append(f)

        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=final_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        print(f"  {table_type}: {len(rows)} rows -> {csv_path.name}")


def write_issues(issues: list[ParseIssue], output_dir: Path) -> None:
    csv_path = output_dir / "qa_issues.csv"
    if not issues:
        csv_path.write_text("", encoding="utf-8-sig")
        return
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["level", "code", "enterprise_name", "source_file", "message"])
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue.as_dict())
    print(f"  qa_issues: {len(issues)} issues")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract structured outlet data from .docx files")
    parser.add_argument("--input-dir", default=None, help="Directory containing .docx files")
    parser.add_argument("--output-dir", default="data/outlet_structured", help="Output directory for CSVs")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N files (0=all)")
    parser.add_argument("--all", action="store_true", help="Process all files (alias for --limit 0)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.all:
        args.limit = 0

    input_dir = detect_input_dir(args.input_dir)
    output_dir = Path(args.output_dir)

    docx_files = sorted(input_dir.glob("*.docx"), key=natural_key)
    if args.limit > 0:
        docx_files = docx_files[: args.limit]

    print(f"Input dir:  {input_dir}")
    print(f"Output dir: {output_dir}")
    print(f"Files to process: {len(docx_files)}")

    all_records: dict[str, list[dict]] = defaultdict(list)
    issues: list[ParseIssue] = []

    for i, fp in enumerate(docx_files, 1):
        print(f"\n[{i}/{len(docx_files)}] {fp.name}")
        records = process_file(fp, issues)
        for k, v in records.items():
            all_records[k].extend(v)

    print(f"\n{'='*60}")
    print("Writing CSVs...")
    write_csvs(all_records, output_dir)
    write_issues(issues, output_dir)

    print(f"\n{'='*60}")
    print("Summary:")
    for t in TYPE_ORDER:
        n = len(all_records.get(t, []))
        if n > 0:
            print(f"  {t}: {n}")
    total_data = sum(len(all_records.get(t, [])) for t in TYPE_ORDER if t != "enterprise_profile")
    total_enterprises = len(all_records.get("enterprise_profile", []))
    print(f"  Total enterprises: {total_enterprises}")
    print(f"  Total data rows: {total_data}")
    unknown = len(all_records.get("unknown_table", []))
    if total_data > 0:
        print(f"  Unknown table rate: {unknown}/{total_data} = {unknown/total_data:.1%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
