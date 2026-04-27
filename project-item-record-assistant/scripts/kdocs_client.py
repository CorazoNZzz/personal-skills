#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from parser import EXPECTED_HEADERS, tab_row


DOC_NAME = "项目推进与留痕台账"
DOC_LINK = "https://www.kdocs.cn/l/crcZHpAS41uj"
DOC_LINK_ID = "crcZHpAS41uj"
SHEET_NAME = "事项总表"
DEFAULT_HEADER_ROW = 2
MAX_WRITE_COLUMNS = 100
DEFAULT_MCPORTER_CLI = "/Users/corazon/Library/Application Support/QClaw/npm-global/lib/node_modules/mcporter/dist/cli.js"
LEGACY_MCPORTER_CLI = "/Users/corazon/Library/Application Support/QClaw/npm-global/node_modules/mcporter/dist/cli.js"


class KDocsError(RuntimeError):
    pass


def to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("cellText", "originalCellValue", "displayValue", "display", "text", "value", "formula"):
            if value.get(key) is not None:
                return to_text(value.get(key))
    return str(value)


def load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise KDocsError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise KDocsError(f"config must be a JSON object: {path}")
    return data


def parse_range_cells(stdout: str) -> Dict[Tuple[int, int], str]:
    """Parse kdocs 0-based API coordinates into visible spreadsheet coordinates.

    The public client works with the row/column numbers users see in the sheet
    UI: A1 is (1, 1). OpenClaw kdocs `sheet.*` APIs use 0-based rowFrom/colFrom
    and return 0-based coordinates, so the conversion is always +1 here.
    """
    raw = stdout.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise KDocsError(f"cannot parse kdocs response as JSON: {exc}") from exc

    range_data = (
        (((data.get("data") or {}).get("detail") or {}).get("rangeData"))
        or data.get("rangeData")
        or ((data.get("detail") or {}).get("rangeData") if isinstance(data.get("detail"), dict) else None)
    )
    cells: Dict[Tuple[int, int], str] = {}
    if isinstance(range_data, list):
        for cell in range_data:
            if not isinstance(cell, dict):
                continue
            try:
                api_row = cell.get("originRow", cell.get("rowFrom"))
                api_col = cell.get("originCol", cell.get("colFrom"))
                row = int(api_row) + 1
                col = int(api_col) + 1
            except Exception:
                continue
            value = (
                to_text(cell.get("cellText"))
                or to_text(cell.get("originalCellValue"))
                or to_text(cell.get("displayValue"))
                or to_text((cell.get("understandableType") or {}).get("value"))
            )
            cells[(row, col)] = value
    return cells


def run_cmd(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def response_detail(stdout: str) -> Dict[str, Any]:
    raw = stdout.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise KDocsError(f"cannot parse kdocs response as JSON: {exc}") from exc
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    if isinstance(inner, dict):
        nested = inner.get("data")
        if isinstance(nested, dict):
            return nested
        detail = inner.get("detail")
        if isinstance(detail, dict):
            return detail
    detail = data.get("detail")
    return detail if isinstance(detail, dict) else data


class SheetBackend:
    def read_range(self, row_from: int, row_to: int, col_from: int, col_to: int) -> Dict[Tuple[int, int], str]:
        raise NotImplementedError

    def write_row(self, row: int, values: List[str]) -> None:
        raise NotImplementedError


class MockBackend(SheetBackend):
    def __init__(self, path: Path):
        self.path = path
        self.data = load_json_file(path) if path.exists() else {"cells": {}}
        self.data.setdefault("cells", {})

    def _key(self, row: int, col: int) -> str:
        return f"{row},{col}"

    def read_range(self, row_from: int, row_to: int, col_from: int, col_to: int) -> Dict[Tuple[int, int], str]:
        out: Dict[Tuple[int, int], str] = {}
        for row in range(row_from, row_to + 1):
            for col in range(col_from, col_to + 1):
                value = self.data.get("cells", {}).get(self._key(row, col), "")
                out[(row, col)] = to_text(value)
        return out

    def write_row(self, row: int, values: List[str]) -> None:
        for idx, value in enumerate(values, start=1):
            self.data["cells"][self._key(row, idx)] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


class McporterBackend(SheetBackend):
    def __init__(self, config: Dict[str, Any]):
        self.server = str(config.get("mcporter_server") or "kdocs-qclaw").strip()
        self.drive_id = str(config.get("drive_id") or "").strip()
        self.file_id = str(config.get("file_id") or "").strip()
        self.sheet_id = str(config.get("sheet_id") or "").strip()
        self.link_id = str(config.get("link_id") or DOC_LINK_ID).strip()
        self.sheet_name = str(config.get("sheet_name") or SHEET_NAME).strip()
        self.api_index_base = int(config.get("api_index_base", config.get("index_base", 0)))
        cli = str(
            config.get("mcporter_cli")
            or os.environ.get("MCPORTER_CLI")
            or DEFAULT_MCPORTER_CLI
        )
        if not Path(cli).exists() and Path(LEGACY_MCPORTER_CLI).exists():
            cli = LEGACY_MCPORTER_CLI
        self.mcporter_cli = cli
        if not Path(self.mcporter_cli).exists():
            raise KDocsError(f"mcporter CLI not found: {self.mcporter_cli}")
        if not self.server:
            raise KDocsError("mcporter_server is required")
        if self.api_index_base != 0:
            raise KDocsError("kdocs sheet API 使用 0-based 坐标，请将 api_index_base/index_base 配置为 0 或移除该配置。")
        self._resolve_file_and_sheet()

    def _mcporter_call(self, tool: str, args: List[str]) -> subprocess.CompletedProcess[str]:
        return run_cmd(["node", self.mcporter_cli, "call", self.server, tool, *args, "--output", "json"])

    def _resolve_file_and_sheet(self) -> None:
        if not self.file_id:
            if not self.link_id:
                raise KDocsError("未能打开金山文档，请检查链接或授权状态：缺少 file_id/link_id。")
            proc = self._mcporter_call("get_share_info", [f"link_id={self.link_id}"])
            if proc.returncode != 0:
                raise KDocsError(f"未能打开金山文档，请检查链接或授权状态：{proc.stderr.strip() or proc.stdout.strip()}")
            detail = response_detail(proc.stdout)
            self.file_id = str(detail.get("file_id") or "").strip()
            self.drive_id = str(detail.get("drive_id") or self.drive_id).strip()
            if not self.file_id:
                raise KDocsError("未能打开金山文档，请检查链接或授权状态：get_share_info 未返回 file_id。")

        if not self.sheet_id:
            proc = self._mcporter_call("sheet.get_sheets_info", [f"file_id={self.file_id}"])
            if proc.returncode != 0:
                raise KDocsError(f"未找到事项总表，请检查 sheet 名称是否一致：{proc.stderr.strip() or proc.stdout.strip()}")
            detail = response_detail(proc.stdout)
            sheets = detail.get("sheetsInfo")
            if not isinstance(sheets, list):
                raise KDocsError("未找到事项总表，请检查 sheet 名称是否一致：get_sheets_info 未返回 sheetsInfo。")
            for sheet in sheets:
                if isinstance(sheet, dict) and sheet.get("sheetName") == self.sheet_name:
                    self.sheet_id = str(sheet.get("sheetId") or "").strip()
                    break
            if not self.sheet_id:
                names = [str(s.get("sheetName")) for s in sheets if isinstance(s, dict)]
                raise KDocsError(f"未找到事项总表，请检查 sheet 名称是否一致。当前 sheet：{'、'.join(names)}")

    @staticmethod
    def _to_api_index(visible_index: int) -> int:
        api_index = int(visible_index) - 1
        if api_index < 0:
            raise KDocsError(f"invalid visible row/col index: {visible_index}")
        return api_index

    def _range_json(self, row_from: int, row_to: int, col_from: int, col_to: int) -> str:
        return json.dumps(
            {
                "rowFrom": self._to_api_index(row_from),
                "rowTo": self._to_api_index(row_to),
                "colFrom": self._to_api_index(col_from),
                "colTo": self._to_api_index(col_to),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def read_range(self, row_from: int, row_to: int, col_from: int, col_to: int) -> Dict[Tuple[int, int], str]:
        proc = self._mcporter_call(
            "sheet.get_range_data",
            [
            f"file_id={self.file_id}",
            f"sheetId={self.sheet_id}",
            f"range={self._range_json(row_from, row_to, col_from, col_to)}",
            ],
        )
        if proc.returncode != 0:
            raise KDocsError(
                f"读取金山文档失败：range=({row_from},{col_from})-({row_to},{col_to})；"
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return parse_range_cells(proc.stdout)

    def write_row(self, row: int, values: List[str]) -> None:
        if len(values) > MAX_WRITE_COLUMNS:
            raise KDocsError(f"写入列数超过限制：{len(values)} > {MAX_WRITE_COLUMNS}")
        range_data = []
        row0 = self._to_api_index(row)
        for offset, value in enumerate(values):
            col0 = self._to_api_index(offset + 1)
            range_data.append(
                {
                    "opType": "formula",
                    "rowFrom": row0,
                    "rowTo": row0,
                    "colFrom": col0,
                    "colTo": col0,
                    "formula": value,
                }
            )
        proc = self._mcporter_call(
            "sheet.update_range_data",
            [
            f"file_id={self.file_id}",
            f"sheetId={self.sheet_id}",
            "rangeData=" + json.dumps(range_data, ensure_ascii=False, separators=(",", ":")),
            ],
        )
        if proc.returncode != 0:
            raise KDocsError(
                f"写入金山文档失败：target_row={row}, target_cols=1-{len(values)}；"
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )


@dataclass
class AddResult:
    number: str
    row_number: int


class KDocsClient:
    def __init__(self, backend: SheetBackend, max_scan_rows: int = 1000, header_row: int = DEFAULT_HEADER_ROW):
        self.backend = backend
        self.max_scan_rows = max_scan_rows
        self.header_row = int(header_row)
        if self.header_row < 1:
            raise KDocsError("header_row must be >= 1")

    def read_table_cells(self) -> Dict[Tuple[int, int], str]:
        return self.backend.read_range(1, self.max_scan_rows, 1, len(EXPECTED_HEADERS))

    def validate_header(self, cells: Dict[Tuple[int, int], str]) -> List[str]:
        actual = [to_text(cells.get((self.header_row, col), "")).strip() for col in range(1, len(EXPECTED_HEADERS) + 1)]
        if actual != EXPECTED_HEADERS:
            raise KDocsError(
                "事项总表字段与 Skill 配置不一致，请检查表头顺序。\n"
                f"表头检查行：第 {self.header_row} 行\n"
                f"当前识别到的表头：{'、'.join(actual)}\n"
                f"期望表头：{'、'.join(EXPECTED_HEADERS)}"
            )
        return actual

    def next_number_and_row(self, cells: Dict[Tuple[int, int], str]) -> Tuple[str, int]:
        max_num = 0
        number_width: Optional[int] = None
        last_row = self.header_row
        for row in range(self.header_row + 1, self.max_scan_rows + 1):
            row_values = [to_text(cells.get((row, col), "")).strip() for col in range(1, len(EXPECTED_HEADERS) + 1)]
            if any(row_values):
                last_row = row
            m = re.fullmatch(r"SX-(\d+)", row_values[0] if row_values else "")
            if m:
                digits = m.group(1)
                number_width = max(number_width or 0, len(digits))
                max_num = max(max_num, int(digits))
        number_width = number_width or 4
        return f"SX-{max_num + 1:0{number_width}d}", last_row + 1

    def add_item(self, draft: Dict[str, Any]) -> AddResult:
        cells = self.read_table_cells()
        self.validate_header(cells)
        number, row_number = self.next_number_and_row(cells)
        values = tab_row(draft, number=number).split("\t")
        if len(values) != len(EXPECTED_HEADERS):
            raise KDocsError("待写入字段数量不等于 15，已停止写入。")
        self.backend.write_row(row_number, values)
        return AddResult(number=number, row_number=row_number)


def backend_from_args(backend_name: str, config_path: Optional[str] = None, mock_file: Optional[str] = None) -> Tuple[SheetBackend, int, int]:
    config = load_json_file(Path(config_path).expanduser()) if config_path else {}
    max_scan_rows = int(config.get("max_scan_rows", 1000))
    header_row = int(config.get("header_row", DEFAULT_HEADER_ROW))
    if backend_name == "mock":
        path = Path(mock_file or config.get("mock_file") or Path(__file__).resolve().parents[1] / "data" / "mock_kdocs.json")
        return MockBackend(path), max_scan_rows, header_row
    if backend_name == "mcporter":
        return McporterBackend(config), max_scan_rows, header_row
    raise KDocsError(f"unsupported backend: {backend_name}")
