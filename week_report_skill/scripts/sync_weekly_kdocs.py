#!/usr/bin/env python3
"""Aggregate weekly daily records and append into KDocs weekly report cells."""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


DEFAULT_FILE_ID = "bMVCNhm4Q9Mr8yLThHc6rxNE6kiJZ6TE7"
DEFAULT_DRIVE_ID = "2534342736"
DEFAULT_SHEET_ID = 4
DEFAULT_SHEET_NAME = "2026年"
DEFAULT_LATEST_VERSION_COL = 5


class SkillError(Exception):
    pass


def now_shanghai_date() -> dt.date:
    if ZoneInfo is None:
        return dt.date.today()
    return dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()


def default_week_range(today: dt.date) -> Tuple[dt.date, dt.date]:
    monday = today - dt.timedelta(days=today.weekday())
    friday = monday + dt.timedelta(days=4)
    return monday, friday


def default_archive_file() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "daily_records.jsonl"


def default_preview_file() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "last_preview.json"


def default_credentials_file() -> Path:
    return Path(__file__).resolve().parents[2] / "openclaw-daily-report" / ".local-secrets.json"


def parse_date(raw: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except Exception as exc:
        raise SkillError(f"invalid date: {raw}; expected YYYY-MM-DD") from exc


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_cmd_template(raw: Any, key_name: str) -> str:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise SkillError(f"{key_name} template is empty")
        return text
    if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        return json.dumps(raw, ensure_ascii=False)
    raise SkillError(f"{key_name} template must be string or string[]")


def load_cmd_templates_from_file(path: Path) -> Dict[str, str]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise SkillError("template file must be JSON object")
    out: Dict[str, str] = {}
    if "read_cell_cmd_template" in data:
        out["read_cell_cmd_template"] = normalize_cmd_template(data["read_cell_cmd_template"], "read_cell_cmd_template")
    if "write_cell_cmd_template" in data:
        out["write_cell_cmd_template"] = normalize_cmd_template(data["write_cell_cmd_template"], "write_cell_cmd_template")
    return out


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
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
            raise SkillError(f"archive parse failed at line {line_no}") from exc
        if isinstance(obj, dict):
            records.append(obj)
    return records


def to_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def to_float(v: Any) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except Exception:
        return 0.0


def load_local_credentials(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    data = load_json(path)
    if isinstance(data, dict):
        return data
    raise SkillError("credentials file must be a JSON object")


def is_success_code(code: Any) -> bool:
    return str(code).strip() in {"0", "200"}


def api_login(api_base: str, username: str, password: str, timeout: int = 30) -> str:
    url = f"{api_base.rstrip('/')}/v1/auth/login"
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={"username": username, "password": password},
        timeout=timeout,
    )
    payload = None
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if resp.status_code >= 400:
        raise SkillError(f"login failed [{resp.status_code}] {resp.text}")
    if not isinstance(payload, dict) or not is_success_code(payload.get("code")):
        raise SkillError(f"login returned non-success: {payload}")

    token = to_text((payload.get("data") or {}).get("access_token"))
    if not token:
        raise SkillError("login succeeded but access_token is empty")
    return token


def api_get_my_projects(api_base: str, token: str, timeout: int = 30) -> List[Dict[str, Any]]:
    url = f"{api_base.rstrip('/')}/v1/daily-reports/my-projects"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    payload = None
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if resp.status_code >= 400:
        raise SkillError(f"my-projects failed [{resp.status_code}] {resp.text}")
    if not isinstance(payload, dict) or not is_success_code(payload.get("code")):
        raise SkillError(f"my-projects returned non-success: {payload}")

    data = payload.get("data") or []
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    return []


def build_project_id_name_map(credentials: Dict[str, Any], explicit_api_base: str = "") -> Dict[int, str]:
    api_base = to_text(explicit_api_base) or to_text(credentials.get("api_base"))
    username = to_text(credentials.get("login_username"))
    password = to_text(credentials.get("password"))
    if not (api_base and username and password):
        return {}

    try:
        token = api_login(api_base=api_base, username=username, password=password)
        projects = api_get_my_projects(api_base=api_base, token=token)
    except Exception as exc:
        print(f"[warn] failed to load project list from daily API: {exc}", file=sys.stderr)
        return {}

    out: Dict[int, str] = {}
    for p in projects:
        pid = p.get("id")
        pname = to_text(p.get("project_name"))
        if pid is None or not pname:
            continue
        try:
            out[int(pid)] = pname
        except Exception:
            continue
    return out


def resolve_project_name(entry: Dict[str, Any], project_map: Dict[int, str]) -> str:
    name = to_text(entry.get("project_name"))
    if name:
        return name
    pid = entry.get("project_id")
    if pid is not None:
        try:
            pid_int = int(pid)
            if pid_int in project_map:
                return project_map[pid_int]
            return f"项目#{pid_int}"
        except Exception:
            pass
    return "学习或其他"


def collect_range_records(records: List[Dict[str, Any]], start: dt.date, end: dt.date) -> List[Dict[str, Any]]:
    picked: List[Dict[str, Any]] = []
    for r in records:
        date_raw = to_text(r.get("report_date"))
        if not date_raw:
            continue
        try:
            d = parse_date(date_raw)
        except SkillError:
            continue
        if start <= d <= end:
            rr = dict(r)
            rr["report_date"] = d.isoformat()
            picked.append(rr)
    picked.sort(key=lambda x: x["report_date"])
    return picked


def build_weekly_summary(records: List[Dict[str, Any]], project_map: Dict[int, str], start: dt.date, end: dt.date) -> str:
    lines: List[str] = [f"汇总周期：{start.isoformat()} ~ {end.isoformat()}"]
    total_hours = 0.0
    detail_count = 0

    for r in records:
        report_date = to_text(r.get("report_date"))
        entries = r.get("entries")
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            progress = to_text(e.get("progress_content"))
            hours = to_float(e.get("work_hours"))
            if not progress and hours <= 0:
                continue
            project_name = resolve_project_name(e, project_map)
            total_hours += max(hours, 0)
            detail_count += 1
            progress_text = progress or "（无进展描述）"
            lines.append(f"- {report_date[5:]} {project_name}: {progress_text}（{hours:g}h）")

    lines.insert(1, f"总工时：{total_hours:g}h")
    lines.insert(2, f"有效条目：{detail_count}")
    if detail_count == 0:
        lines.append("- 本周期未找到可用日报记录")
    return "\n".join(lines).strip()


def merge_append(existing: str, incoming: str) -> str:
    old = to_text(existing)
    new = to_text(incoming)
    if not old:
        return new
    if not new:
        return old
    if new in old:
        return old
    return f"{old}\n{new}".strip()


def normalize_lookup_text(raw: str) -> str:
    s = unicodedata.normalize("NFKC", to_text(raw)).lower()
    # Keep Chinese/letters/numbers, strip punctuation and spaces for robust matching.
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)


def format_row_candidates(rows: List[Tuple[int, str]], limit: int = 10) -> str:
    preview = rows[:limit]
    body = ", ".join([f"{r}:'{v}'" for r, v in preview])
    if len(rows) > limit:
        body += f", ... (+{len(rows) - limit} more)"
    return body


def resolve_target_row(
    backend: "SheetBackend",
    target_row: Optional[int],
    project_name: str,
    project_col: int,
    scan_row_from: int,
    scan_row_to: int,
) -> Dict[str, Any]:
    if target_row is not None:
        return {"row": int(target_row), "mode": "manual-target-row"}

    desired = normalize_lookup_text(project_name)
    if not desired:
        raise SkillError("either --target-row or --project-name is required")

    exact_matches: List[Tuple[int, str]] = []
    fuzzy_matches: List[Tuple[int, str]] = []
    cells = backend.get_column_cells(scan_row_from, scan_row_to, project_col)
    scanned = len(cells)
    for row, cell_text in cells:
        norm = normalize_lookup_text(cell_text)
        if not norm:
            continue
        if norm == desired:
            exact_matches.append((row, cell_text))
        elif desired in norm or norm in desired:
            fuzzy_matches.append((row, cell_text))

    if len(exact_matches) == 1:
        row, val = exact_matches[0]
        return {
            "row": row,
            "mode": "auto-project-name-exact",
            "matched_project_name": val,
            "scanned_rows": scanned,
            "project_col": project_col,
            "scan_row_from": scan_row_from,
            "scan_row_to": scan_row_to,
        }
    if len(exact_matches) > 1:
        raise SkillError(
            "project-name exact match is ambiguous, candidates: "
            + format_row_candidates(exact_matches)
            + "; use --target-row to override"
        )

    if len(fuzzy_matches) == 1:
        row, val = fuzzy_matches[0]
        return {
            "row": row,
            "mode": "auto-project-name-fuzzy",
            "matched_project_name": val,
            "scanned_rows": scanned,
            "project_col": project_col,
            "scan_row_from": scan_row_from,
            "scan_row_to": scan_row_to,
        }
    if len(fuzzy_matches) > 1:
        raise SkillError(
            "project-name fuzzy match is ambiguous, candidates: "
            + format_row_candidates(fuzzy_matches)
            + "; use --target-row to override"
        )

    raise SkillError(
        f"project-name not found in sheet column {project_col} for rows {scan_row_from}-{scan_row_to}: {project_name}"
    )


def escape_formula_text_piece(s: str) -> str:
    return s.replace('"', '""')


def plain_text_to_formula(s: str) -> str:
    text = to_text(s)
    if not text:
        return '=""'
    parts = text.splitlines()
    if len(parts) == 1:
        return f'="{escape_formula_text_piece(parts[0])}"'
    segs = [f'"{escape_formula_text_piece(p)}"' for p in parts]
    return "=" + "&CHAR(10)&".join(segs)


def formula_to_plain_text(formula: str) -> str:
    f = to_text(formula)
    if not f.startswith("="):
        return f
    body = f[1:]
    parts = body.split("&CHAR(10)&")
    out_lines: List[str] = []
    for p in parts:
        piece = p.strip()
        if len(piece) >= 2 and piece.startswith('"') and piece.endswith('"'):
            piece = piece[1:-1].replace('""', '"')
        out_lines.append(piece)
    return "\n".join(out_lines).strip()


def prompt_yes(question: str, expected: str = "YES") -> bool:
    answer = input(question).strip().upper()
    return answer == expected.upper()


def prompt_multiline(header: str) -> str:
    print(header)
    print("（逐行输入，空行结束）")
    lines: List[str] = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def parse_template_output_value(stdout: str, row0: Optional[int] = None, col0: Optional[int] = None) -> str:
    raw = stdout.strip()
    if not raw:
        return ""

    try:
        data = json.loads(raw)
    except Exception:
        return raw

    # Prefer sheet.get_range_data payload first.
    if isinstance(data, dict):
        detail = ((data.get("data") or {}).get("detail") or {})
        if isinstance(detail, dict) and "rangeData" in detail:
            range_data = detail.get("rangeData")
            if not isinstance(range_data, list) or not range_data:
                return ""
            cells = [c for c in range_data if isinstance(c, dict)]
            if row0 is not None and col0 is not None:
                matched = [
                    c
                    for c in cells
                    if int(c.get("originRow", -1)) == int(row0) and int(c.get("originCol", -1)) == int(col0)
                ]
                if matched:
                    cells = matched
            if cells:
                cell = cells[0]
                for k in ("cellText", "originalCellValue", "displayValue", "display", "text", "value", "formula"):
                    if cell.get(k) is not None:
                        return to_text(cell.get(k))
                understandable = cell.get("understandableType")
                if isinstance(understandable, dict) and understandable.get("value") is not None:
                    return to_text(understandable.get("value"))
            return ""

    preferred_keys = [
        "cellText",
        "originalCellValue",
        "displayValue",
        "display",
        "text",
        "value",
        "cellValue",
        "formula",
        "content",
    ]

    def pick(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            for k in preferred_keys:
                if k in obj and obj.get(k) is not None:
                    return to_text(obj.get(k))
            for v in obj.values():
                got = pick(v)
                if got is not None:
                    return got
        elif isinstance(obj, list):
            for item in obj:
                got = pick(item)
                if got is not None:
                    return got
        elif isinstance(obj, str):
            return obj
        return None

    return pick(data) or ""


def run_templated_command(template: str, mapping: Dict[str, str]) -> subprocess.CompletedProcess:
    template = template.strip()
    if not template:
        raise SkillError("command template is empty")

    if template.startswith("["):
        try:
            arr = json.loads(template)
        except Exception as exc:
            raise SkillError("command template JSON array parse failed") from exc
        if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
            raise SkillError("command template JSON array must be string list")
        cmd = [x.format(**mapping) for x in arr]
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    cmd = template.format(**mapping)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True)


@dataclass
class BackendContext:
    file_id: str
    drive_id: str
    sheet_id: str


class SheetBackend:
    def get_cell(self, row: int, col: int) -> str:
        raise NotImplementedError

    def set_cell_formula(self, row: int, col: int, formula: str) -> None:
        raise NotImplementedError

    def get_column_cells(self, row_from: int, row_to: int, col: int) -> List[Tuple[int, str]]:
        out: List[Tuple[int, str]] = []
        for row in range(row_from, row_to + 1):
            out.append((row, self.get_cell(row, col)))
        return out


class MockBackend(SheetBackend):
    def __init__(self, mock_file: Path):
        self.mock_file = mock_file
        if self.mock_file.exists():
            self.data = load_json(self.mock_file)
            if not isinstance(self.data, dict):
                raise SkillError("mock file must be a JSON object")
        else:
            self.data = {"cells": {}}
        self.data.setdefault("cells", {})

    def _key(self, row: int, col: int) -> str:
        return f"{row},{col}"

    def get_cell(self, row: int, col: int) -> str:
        key = self._key(row, col)
        value = self.data.get("cells", {}).get(key, "")
        if isinstance(value, dict):
            return to_text(value.get("display") or value.get("value") or value.get("formula") or "")
        return to_text(value)

    def set_cell_formula(self, row: int, col: int, formula: str) -> None:
        key = self._key(row, col)
        self.data["cells"][key] = {
            "formula": formula,
            "display": formula_to_plain_text(formula),
        }
        self.mock_file.parent.mkdir(parents=True, exist_ok=True)
        self.mock_file.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


class McporterTemplateBackend(SheetBackend):
    def __init__(
        self,
        context: BackendContext,
        read_template: str,
        write_template: str,
        index_base: int = 1,
    ):
        self.context = context
        self.read_template = read_template
        self.write_template = write_template
        self.index_base = int(index_base)
        if self.index_base not in (0, 1):
            raise SkillError("index_base must be 0 or 1")

    def _mapping(
        self,
        row: int,
        col: int,
        formula: str = "",
        row_to: Optional[int] = None,
        col_to: Optional[int] = None,
    ) -> Dict[str, str]:
        row_to = int(row if row_to is None else row_to)
        col_to = int(col if col_to is None else col_to)
        row0_from = int(row) - self.index_base
        row0_to = int(row_to) - self.index_base
        col0_from = int(col) - self.index_base
        col0_to = int(col_to) - self.index_base
        if row0_from < 0 or row0_to < 0 or col0_from < 0 or col0_to < 0:
            raise SkillError(
                f"invalid row/col after index conversion: "
                f"row={row}, row_to={row_to}, col={col}, col_to={col_to}, index_base={self.index_base}"
            )
        if row0_to < row0_from or col0_to < col0_from:
            raise SkillError("invalid range: row_to/col_to must be >= row/col")
        return {
            "file_id": self.context.file_id,
            "drive_id": self.context.drive_id,
            "sheet_id": self.context.sheet_id,
            "row": str(row),
            "row_to": str(row_to),
            "col": str(col),
            "col_to": str(col_to),
            "row0": str(row0_from),
            "col0": str(col0_from),
            "row0_from": str(row0_from),
            "row0_to": str(row0_to),
            "col0_from": str(col0_from),
            "col0_to": str(col0_to),
            "formula": formula,
            "formula_json": json.dumps(formula, ensure_ascii=False),
            "op_type": "formula",
        }

    def get_cell(self, row: int, col: int) -> str:
        mapping = self._mapping(row=row, col=col, row_to=row, col_to=col)
        proc = run_templated_command(self.read_template, mapping)
        if proc.returncode != 0:
            raise SkillError(
                f"read cell failed (row={row}, col={col}): {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return parse_template_output_value(proc.stdout, row0=int(mapping["row0"]), col0=int(mapping["col0"]))

    def set_cell_formula(self, row: int, col: int, formula: str) -> None:
        proc = run_templated_command(
            self.write_template,
            self._mapping(row=row, col=col, formula=formula, row_to=row, col_to=col),
        )
        if proc.returncode != 0:
            raise SkillError(
                f"write cell failed (row={row}, col={col}): {proc.stderr.strip() or proc.stdout.strip()}"
            )

    def get_column_cells(self, row_from: int, row_to: int, col: int) -> List[Tuple[int, str]]:
        mapping = self._mapping(row=row_from, col=col, row_to=row_to, col_to=col)
        proc = run_templated_command(self.read_template, mapping)
        if proc.returncode != 0:
            raise SkillError(
                f"read column failed (row_from={row_from}, row_to={row_to}, col={col}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        try:
            payload = json.loads(proc.stdout.strip() or "{}")
        except Exception as exc:
            raise SkillError(f"cannot parse read-column output as JSON: {exc}") from exc

        range_data = (((payload.get("data") or {}).get("detail") or {}).get("rangeData"))
        cell_map: Dict[int, str] = {}
        if isinstance(range_data, list):
            for cell in range_data:
                if not isinstance(cell, dict):
                    continue
                try:
                    origin_row0 = int(cell.get("originRow"))
                    row = origin_row0 + self.index_base
                except Exception:
                    continue
                text = (
                    to_text(cell.get("cellText"))
                    or to_text(cell.get("originalCellValue"))
                    or to_text(((cell.get("understandableType") or {}).get("value")))
                )
                cell_map[row] = text

        out: List[Tuple[int, str]] = []
        for row in range(row_from, row_to + 1):
            out.append((row, cell_map.get(row, "")))
        return out


def parse_args() -> argparse.Namespace:
    today = now_shanghai_date()
    d_start, d_end = default_week_range(today)

    parser = argparse.ArgumentParser(description="Aggregate daily records and append into KDocs weekly report")
    parser.add_argument("--daily-archive-file", default=str(default_archive_file()), help="daily records JSONL")
    parser.add_argument("--start-date", default=d_start.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=d_end.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--next-week-plan", default="", help="next-week plan text")
    parser.add_argument("--next-week-plan-file", default="", help="txt/md file for next-week plan")

    parser.add_argument("--target-row", type=int, default=0, help="target row index in KDocs sheet (manual override)")
    parser.add_argument("--project-name", default="", help="project name used to auto-locate row when target-row is not set")
    parser.add_argument(
        "--project-col",
        type=int,
        default=2,
        help="project name column index for auto-locate (same index-base as row/col args; default: 2 for current sheet)",
    )
    parser.add_argument("--scan-row-from", type=int, default=0, help="auto-locate scan start row (same index-base)")
    parser.add_argument("--scan-row-to", type=int, default=200, help="auto-locate scan end row (same index-base)")
    parser.add_argument("--file-id", default=DEFAULT_FILE_ID)
    parser.add_argument("--drive-id", default=DEFAULT_DRIVE_ID)
    parser.add_argument("--sheet-id", type=int, default=DEFAULT_SHEET_ID)
    parser.add_argument("--sheet-name", default=DEFAULT_SHEET_NAME)

    parser.add_argument("--latest-version-col", type=int, default=DEFAULT_LATEST_VERSION_COL)
    parser.add_argument("--this-week-col", type=int, default=0, help="override this-week summary column")
    parser.add_argument("--next-week-col", type=int, default=0, help="override next-week plan column")
    parser.add_argument("--index-base", type=int, choices=[0, 1], default=1, help="input row/col index base (default: 1)")

    parser.add_argument("--credentials-file", default=str(default_credentials_file()), help="daily API secrets JSON")
    parser.add_argument("--api-base", default="", help="override daily API base")

    parser.add_argument("--backend", choices=["mcporter", "mock"], default="mcporter")
    parser.add_argument("--mock-sheet-file", default=str(Path(__file__).resolve().parents[1] / "data" / "mock_sheet.json"))
    parser.add_argument(
        "--mcporter-template-file",
        default="",
        help="JSON file containing read_cell_cmd_template/write_cell_cmd_template",
    )
    parser.add_argument(
        "--read-cell-cmd-template",
        default="",
        help="mcporter read template; supports IDs + {row}/{row_to}/{col}/{col_to}/{row0_from}/{row0_to}/{col0_from}/{col0_to}",
    )
    parser.add_argument(
        "--write-cell-cmd-template",
        default="",
        help="mcporter write template; supports {formula},{formula_json},{op_type} and IDs/row/col/row0/col0",
    )

    parser.add_argument("--apply", action="store_true", help="actually write into KDocs")
    parser.add_argument("--confirm-range", default="", help="set YES to bypass interactive range confirmation")
    parser.add_argument("--confirm-write", default="", help="set WRITE to bypass interactive final confirmation")
    parser.add_argument("--preview-file", default=str(default_preview_file()), help="preview json output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if start_date > end_date:
        raise SkillError("start-date cannot be later than end-date")

    min_row = 3 if args.index_base == 1 else 2
    target_row: Optional[int] = None
    if int(args.target_row) > 0:
        target_row = int(args.target_row)
        if target_row < min_row:
            raise SkillError(f"target-row must be >= {min_row} when --index-base={args.index_base}")

    this_week_col = args.this_week_col if args.this_week_col > 0 else args.latest_version_col + 1
    next_week_col = args.next_week_col if args.next_week_col > 0 else args.latest_version_col + 2
    project_col = int(args.project_col) if int(args.project_col) > 0 else (2 if args.index_base == 1 else 1)
    scan_row_from = int(args.scan_row_from) if int(args.scan_row_from) > 0 else min_row
    scan_row_to = int(args.scan_row_to)
    if scan_row_to < scan_row_from:
        raise SkillError("scan-row-to cannot be earlier than scan-row-from")

    if args.confirm_range.upper() != "YES":
        ok = prompt_yes(
            f"确认汇总范围 {start_date.isoformat()} ~ {end_date.isoformat()} 吗？输入 YES 继续：",
            expected="YES",
        )
        if not ok:
            print("已取消：范围未确认")
            return 1

    next_week_plan = to_text(args.next_week_plan)
    if args.next_week_plan_file:
        next_week_plan = Path(args.next_week_plan_file).read_text(encoding="utf-8-sig").strip()
    if not next_week_plan:
        next_week_plan = prompt_multiline("请输入下周工作计划")
    if not next_week_plan:
        raise SkillError("next-week-plan is required")

    archive_path = Path(args.daily_archive_file).expanduser().resolve()
    records = load_jsonl(archive_path)
    picked_records = collect_range_records(records, start=start_date, end=end_date)

    credentials_path = Path(args.credentials_file).expanduser().resolve() if args.credentials_file else None
    credentials = load_local_credentials(credentials_path)
    project_map = build_project_id_name_map(credentials=credentials, explicit_api_base=args.api_base)

    weekly_summary = build_weekly_summary(
        records=picked_records,
        project_map=project_map,
        start=start_date,
        end=end_date,
    )

    backend: SheetBackend
    if args.backend == "mock":
        backend = MockBackend(Path(args.mock_sheet_file).expanduser().resolve())
    else:
        read_template = (args.read_cell_cmd_template or "").strip()
        write_template = (args.write_cell_cmd_template or "").strip()
        if args.mcporter_template_file:
            template_path = Path(args.mcporter_template_file).expanduser().resolve()
            loaded = load_cmd_templates_from_file(template_path)
            if not read_template:
                read_template = loaded.get("read_cell_cmd_template", "")
            if not write_template:
                write_template = loaded.get("write_cell_cmd_template", "")

        if not read_template or not write_template:
            raise SkillError(
                "mcporter backend requires read/write templates: "
                "--read-cell-cmd-template + --write-cell-cmd-template "
                "or --mcporter-template-file"
            )
        backend = McporterTemplateBackend(
            context=BackendContext(file_id=args.file_id, drive_id=args.drive_id, sheet_id=str(args.sheet_id)),
            read_template=read_template,
            write_template=write_template,
            index_base=args.index_base,
        )

    row_resolution = resolve_target_row(
        backend=backend,
        target_row=target_row,
        project_name=to_text(args.project_name),
        project_col=project_col,
        scan_row_from=scan_row_from,
        scan_row_to=scan_row_to,
    )
    resolved_row = int(row_resolution["row"])

    existing_this = backend.get_cell(resolved_row, this_week_col)
    existing_next = backend.get_cell(resolved_row, next_week_col)

    merged_this = merge_append(existing_this, weekly_summary)
    merged_next = merge_append(existing_next, next_week_plan)

    preview = {
        "document": {
            "file_id": args.file_id,
            "drive_id": args.drive_id,
            "sheet_id": args.sheet_id,
            "sheet_name": args.sheet_name,
        },
        "range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "target": {
            "index_base": args.index_base,
            "row": resolved_row,
            "latest_version_col": args.latest_version_col,
            "this_week_col": this_week_col,
            "next_week_col": next_week_col,
            "row_resolution": row_resolution,
        },
        "preview": {
            "existing_this_week": existing_this,
            "incoming_this_week": weekly_summary,
            "merged_this_week": merged_this,
            "existing_next_week": existing_next,
            "incoming_next_week": next_week_plan,
            "merged_next_week": merged_next,
        },
        "stats": {
            "daily_records_total": len(records),
            "daily_records_in_range": len(picked_records),
            "project_map_size": len(project_map),
            "apply": bool(args.apply),
            "backend": args.backend,
        },
    }

    preview_path = Path(args.preview_file).expanduser().resolve()
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 周报写入预览 ===")
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    print(f"预览已保存: {preview_path}")

    if not args.apply:
        print("当前为预览模式，未写入金山文档。")
        return 0

    if args.confirm_write.upper() != "WRITE":
        ok = prompt_yes("确认写入金山文档吗？输入 WRITE 执行写入：", expected="WRITE")
        if not ok:
            print("已取消：未确认写入")
            return 1

    formula_this = plain_text_to_formula(merged_this)
    formula_next = plain_text_to_formula(merged_next)

    backend.set_cell_formula(resolved_row, this_week_col, formula_this)
    backend.set_cell_formula(resolved_row, next_week_col, formula_next)

    print(
        json.dumps(
            {
                "status": "written",
                "row": resolved_row,
                "this_week_col": this_week_col,
                "next_week_col": next_week_col,
                "opType": "formula",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SkillError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
