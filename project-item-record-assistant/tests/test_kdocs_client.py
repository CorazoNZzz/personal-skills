#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from kdocs_client import KDocsClient, McporterBackend, MockBackend, parse_range_cells
from parser import EXPECTED_HEADERS


def mock_sheet(cells):
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
    json.dump({"cells": cells}, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


class KDocsClientTest(unittest.TestCase):
    def test_parse_range_cells_converts_api_zero_based_to_visible_coordinates(self):
        payload = {
            "data": {
                "detail": {
                    "rangeData": [
                        {"originRow": 1, "originCol": 0, "cellText": "编号"},
                        {"rowFrom": 2, "colFrom": 14, "cellText": "备注"},
                    ]
                }
            }
        }

        cells = parse_range_cells(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(cells[(2, 1)], "编号")
        self.assertEqual(cells[(3, 15)], "备注")

    def test_mcporter_ranges_use_zero_based_api_coordinates(self):
        backend = McporterBackend({"file_id": "file", "sheet_id": "1"})

        range_arg = json.loads(backend._range_json(2, 7, 1, 15))

        self.assertEqual(range_arg, {"rowFrom": 1, "rowTo": 6, "colFrom": 0, "colTo": 14})

    def test_header_row_two_and_sparse_rows_append_after_last_non_empty_row(self):
        cells = {"1,1": "项目推进与留痕台账"}
        for col, header in enumerate(EXPECTED_HEADERS, start=1):
            cells[f"2,{col}"] = header
        cells["3,1"] = "SX-0002"
        cells["3,2"] = "2026-04-20"
        cells["5,1"] = "SX-0009"
        cells["7,3"] = "只有项目名但编号异常"

        path = mock_sheet(cells)
        try:
            client = KDocsClient(MockBackend(path), max_scan_rows=10, header_row=2)
            table_cells = client.read_table_cells()

            client.validate_header(table_cells)
            number, row = client.next_number_and_row(table_cells)

            self.assertEqual(number, "SX-0010")
            self.assertEqual(row, 8)
        finally:
            path.unlink(missing_ok=True)

    def test_number_width_follows_existing_sheet(self):
        cells = {"1,1": "项目推进与留痕台账"}
        for col, header in enumerate(EXPECTED_HEADERS, start=1):
            cells[f"2,{col}"] = header
        cells["3,1"] = "SX-002"
        cells["5,1"] = "SX-004"

        path = mock_sheet(cells)
        try:
            client = KDocsClient(MockBackend(path), max_scan_rows=10, header_row=2)
            number, row = client.next_number_and_row(client.read_table_cells())

            self.assertEqual(number, "SX-005")
            self.assertEqual(row, 6)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
