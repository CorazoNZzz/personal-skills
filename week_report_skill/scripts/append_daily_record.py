#!/usr/bin/env python3
"""Append one day's submitted daily entries into local weekly archive (JSONL)."""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def shanghai_today() -> dt.date:
    if ZoneInfo is None:
        return dt.date.today()
    return dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()


def default_entries_file() -> Path:
    # .../week_report_skill/scripts/append_daily_record.py
    # -> .../openclaw-daily-report/data/today_entries.json
    return Path(__file__).resolve().parents[2] / "openclaw-daily-report" / "data" / "today_entries.json"


def default_archive_file() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "daily_records.jsonl"


def load_entries(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("entries file must be a JSON array")

    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"entry #{idx} must be a JSON object")

        project_id = item.get("project_id")
        project_name = str(item.get("project_name") or "").strip()
        progress_content = str(item.get("progress_content") or "").strip()
        risks_issues = str(item.get("risks_issues") or "").strip()
        work_hours_raw = item.get("work_hours")
        try:
            work_hours = float(work_hours_raw) if work_hours_raw not in (None, "") else 0.0
        except Exception as exc:
            raise ValueError(f"entry #{idx} work_hours invalid: {work_hours_raw}") from exc

        normalized = {
            "project_id": int(project_id) if project_id not in (None, "", "null") else None,
            "project_name": project_name,
            "work_hours": round(work_hours, 2),
            "progress_content": progress_content,
            "risks_issues": risks_issues,
        }
        out.append(normalized)
    return out


def load_existing_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception as exc:
            raise ValueError(f"archive parse failed at line {line_no}") from exc
        if isinstance(obj, dict):
            records.append(obj)
    return records


def write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append one day's daily entries to local weekly archive")
    parser.add_argument("--report-date", default=shanghai_today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--entries-file", default=str(default_entries_file()), help="daily entries JSON file")
    parser.add_argument("--archive-file", default=str(default_archive_file()), help="JSONL archive file")
    parser.add_argument("--source", default="openclaw-daily-report", help="record source tag")
    parser.add_argument("--replace-date", action="store_true", help="replace existing records on same report_date")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_date = dt.date.fromisoformat(args.report_date).isoformat()
    entries_file = Path(args.entries_file).expanduser().resolve()
    archive_file = Path(args.archive_file).expanduser().resolve()

    if not entries_file.exists():
        raise FileNotFoundError(f"entries file not found: {entries_file}")

    entries = load_entries(entries_file)
    existing = load_existing_jsonl(archive_file)

    if args.replace_date:
        existing = [r for r in existing if str(r.get("report_date") or "").strip() != report_date]

    record = {
        "report_date": report_date,
        "entries": entries,
        "source": str(args.source or "").strip() or "openclaw-daily-report",
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "entries_count": len(entries),
    }
    existing.append(record)
    existing.sort(key=lambda r: str(r.get("report_date") or ""))

    write_jsonl(archive_file, existing)
    print(json.dumps({"archive_file": str(archive_file), "report_date": report_date, "entries_count": len(entries)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
