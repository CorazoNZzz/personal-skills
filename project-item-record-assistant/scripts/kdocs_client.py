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
SHEET_NAME = "事项总表"


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


def parse_range_cells(stdout: str, index_base: int = 1) -> Dict[Tuple[int, int], str]:
    raw = stdout.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise KDocsError(f"cannot parse kdocs response as JSON: {exc}") from exc

    range_data = (((data.get("data") or {}).get("detail") or {}).get("rangeData"))
    cells: Dict[Tuple[int, int], str] = {}
    if isinstance(range_data, list):
        for cell in range_data:
            if not isinstance(cell, dict):
                continue
            try:
                row = int(cell.get("originRow")) + index_base
                col = int(cell.get("originCol")) + index_base
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
        self.file_id = str(config.get("file_id") or "").strip()
        self.drive_id = str(config.get("drive_id") or "").strip()
        self.sheet_id = str(config.get("sheet_id") or "").strip()
        self.index_base = int(config.get("index_base", 1))
        self.mcporter_cli = str(
            config.get("mcporter_cli")
            or os.environ.get("MCPORTER_CLI")
            or "/Users/corazon/Library/Application Support/QClaw/npm-global/node_modules/mcporter/dist/cli.js"
        )
        if not self.file_id:
            raise KDocsError("未能打开金山文档，请检查链接或授权状态：缺少 file_id。")
        if not self.sheet_id:
            raise KDocsError("未找到事项总表，请检查 sheet 名称是否一致：缺少 sheet_id。")
        if self.index_base not in (0, 1):
            raise KDocsError("index_base must be 0 or 1")

    def _range_json(self, row_from: int, row_to: int, col_from: int, col_to: int) -> str:
        return json.dumps(
            {
                "rowFrom": row_from - self.index_base,
                "rowTo": row_to - self.index_base,
                "colFrom": col_from - self.index_base,
                "colTo": col_to - self.index_base,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def read_range(self, row_from: int, row_to: int, col_from: int, col_to: int) -> Dict[Tuple[int, int], str]:
        cmd = [
            "node",
            self.mcporter_cli,
            "call",
            "--server",
            "kdocs",
            "--tool",
            "sheet.get_range_data",
            f"file_id={self.file_id}",
            f"sheetId={self.sheet_id}",
            f"range={self._range_json(row_from, row_to, col_from, col_to)}",
            "--output",
            "json",
        ]
        proc = run_cmd(cmd)
        if proc.returncode != 0:
            raise KDocsError(f"读取金山文档失败：{proc.stderr.strip() or proc.stdout.strip()}")
        return parse_range_cells(proc.stdout, index_base=self.index_base)

    def write_row(self, row: int, values: List[str]) -> None:
        range_data = []
        row0 = row - self.index_base
        for offset, value in enumerate(values):
            col0 = offset + 1 - self.index_base
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
        cmd = [
            "node",
            self.mcporter_cli,
            "call",
            "--server",
            "kdocs",
            "--tool",
            "sheet.update_range_data",
            f"file_id={self.file_id}",
            f"sheetId={self.sheet_id}",
            "rangeData=" + json.dumps(range_data, ensure_ascii=False, separators=(",", ":")),
            "--output",
            "json",
        ]
        proc = run_cmd(cmd)
        if proc.returncode != 0:
            raise KDocsError(f"写入金山文档失败：{proc.stderr.strip() or proc.stdout.strip()}")


@dataclass
class AddResult:
    number: str
    row_number: int


class KDocsClient:
    def __init__(self, backend: SheetBackend, max_scan_rows: int = 1000):
        self.backend = backend
        self.max_scan_rows = max_scan_rows

    def read_table_cells(self) -> Dict[Tuple[int, int], str]:
        return self.backend.read_range(1, self.max_scan_rows, 1, len(EXPECTED_HEADERS))

    def validate_header(self, cells: Dict[Tuple[int, int], str]) -> List[str]:
        actual = [to_text(cells.get((1, col), "")).strip() for col in range(1, len(EXPECTED_HEADERS) + 1)]
        if actual != EXPECTED_HEADERS:
            raise KDocsError(
                "事项总表字段与 Skill 配置不一致，请检查表头顺序。\n"
                f"当前识别到的表头：{'、'.join(actual)}\n"
                f"期望表头：{'、'.join(EXPECTED_HEADERS)}"
            )
        return actual

    def next_number_and_row(self, cells: Dict[Tuple[int, int], str]) -> Tuple[str, int]:
        max_num = 0
        last_row = 1
        for row in range(2, self.max_scan_rows + 1):
            row_values = [to_text(cells.get((row, col), "")).strip() for col in range(1, len(EXPECTED_HEADERS) + 1)]
            if any(row_values):
                last_row = row
            m = re.fullmatch(r"SX-(\d{4})", row_values[0] if row_values else "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"SX-{max_num + 1:04d}", last_row + 1

    def add_item(self, draft: Dict[str, Any]) -> AddResult:
        cells = self.read_table_cells()
        self.validate_header(cells)
        number, row_number = self.next_number_and_row(cells)
        values = tab_row(draft, number=number).split("\t")
        if len(values) != len(EXPECTED_HEADERS):
            raise KDocsError("待写入字段数量不等于 15，已停止写入。")
        self.backend.write_row(row_number, values)
        return AddResult(number=number, row_number=row_number)


def backend_from_args(backend_name: str, config_path: Optional[str] = None, mock_file: Optional[str] = None) -> Tuple[SheetBackend, int]:
    config = load_json_file(Path(config_path).expanduser()) if config_path else {}
    max_scan_rows = int(config.get("max_scan_rows", 1000))
    if backend_name == "mock":
        path = Path(mock_file or config.get("mock_file") or Path(__file__).resolve().parents[1] / "data" / "mock_kdocs.json")
        return MockBackend(path), max_scan_rows
    if backend_name == "mcporter":
        return McporterBackend(config), max_scan_rows
    raise KDocsError(f"unsupported backend: {backend_name}")
