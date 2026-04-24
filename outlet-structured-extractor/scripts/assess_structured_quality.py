#!/usr/bin/env python
"""Assess completeness and data quality for structured outlet extraction outputs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

TABLE_FILES = [
    'enterprise_profile.csv',
    'organized_outlet.csv',
    'tank.csv',
    'loading.csv',
    'wastewater_surface.csv',
    'fugitive_source.csv',
    'issue_action.csv',
    'reduction_summary.csv',
    'unknown_table.csv',
    'qa_issues.csv',
]

CHECK_FIELDS = [
    'enterprise_name',
    'source_file',
    'record_type',
    'facility_name_raw',
    'facility_code',
    'process_stage',
    'pollutant_category',
    'monitoring_method',
    'treatment_process',
    'raw_fields',
]


def read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def summarize_table(rows: list[dict]) -> dict:
    if not rows:
        return {'rows': 0, 'columns': [], 'missing': {}}

    cols = list(rows[0].keys())
    missing = {}
    for field in CHECK_FIELDS:
        if field in cols:
            miss = sum(1 for r in rows if not (r.get(field) or '').strip())
            missing[field] = {
                'missing': miss,
                'missing_rate': round(miss / len(rows), 4),
            }

    return {
        'rows': len(rows),
        'columns': cols,
        'missing': missing,
    }


def top_missing_by_file(rows: list[dict], field: str, top_n: int = 10) -> list[dict]:
    counter = Counter()
    for r in rows:
        if not (r.get(field) or '').strip():
            counter[(r.get('source_file') or '').strip()] += 1
    result = []
    for source_file, count in counter.most_common(top_n):
        if source_file:
            result.append({'source_file': source_file, 'missing_count': count})
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Assess extracted outlet structured outputs')
    parser.add_argument('--input-dir', default='data/outlet_structured_full', help='Directory containing CSV outputs')
    parser.add_argument('--write-json', help='Optional path to write assessment JSON')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)

    report = {
        'input_dir': str(input_dir.resolve()) if input_dir.exists() else str(input_dir),
        'tables': {},
        'coverage': {},
        'hotspots': {},
        'unknown_examples': [],
    }

    loaded = {}
    for fn in TABLE_FILES:
        rows = read_csv(input_dir / fn)
        loaded[fn] = rows
        report['tables'][fn] = summarize_table(rows)

    profiles = loaded['enterprise_profile.csv']
    profile_files = {r.get('source_file', '').strip() for r in profiles if (r.get('source_file') or '').strip()}

    record_files = set()
    for fn in [
        'organized_outlet.csv',
        'tank.csv',
        'loading.csv',
        'wastewater_surface.csv',
        'fugitive_source.csv',
        'issue_action.csv',
        'reduction_summary.csv',
        'unknown_table.csv',
    ]:
        for r in loaded[fn]:
            sf = (r.get('source_file') or '').strip()
            if sf:
                record_files.add(sf)

    report['coverage'] = {
        'enterprise_profile_count': len(profile_files),
        'records_source_file_count': len(record_files),
        'files_with_no_records': sorted(list(profile_files - record_files)),
    }

    organized_rows = loaded['organized_outlet.csv']
    loading_rows = loaded['loading.csv']
    report['hotspots'] = {
        'organized_missing_name_top': top_missing_by_file(organized_rows, 'facility_name_raw'),
        'organized_missing_code_top': top_missing_by_file(organized_rows, 'facility_code'),
        'loading_missing_process_stage_top': top_missing_by_file(loading_rows, 'process_stage'),
        'loading_missing_treatment_top': top_missing_by_file(loading_rows, 'treatment_process'),
    }

    for r in loaded['unknown_table.csv'][:10]:
        report['unknown_examples'].append(
            {
                'source_file': r.get('source_file', ''),
                'table_index': r.get('table_index', ''),
                'row_index': r.get('row_index', ''),
                'raw_fields': (r.get('raw_fields') or '')[:240],
            }
        )

    if args.write_json:
        out = Path(args.write_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
