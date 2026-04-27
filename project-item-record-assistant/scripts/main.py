#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from kdocs_client import KDocsClient, KDocsError, backend_from_args
from parser import parse_iso_date, parse_item, render_draft, tab_row, update_draft
from state_store import DraftStore, StateError


DEFAULT_CONFIG_FILE = SCRIPT_DIR.parents[0] / "data" / "config.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="项目事项记录助手")
    parser.add_argument("--state-file", default="", help="草稿状态文件，默认 data/drafts.json")
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("parse_item", aliases=["parse"], help="解析事项草稿，不写入")
    p.add_argument("--text", required=True)
    p.add_argument("--today", default="", help="YYYY-MM-DD，用于测试相对日期")

    p = sub.add_parser("update_draft", aliases=["update"], help="修改当前草稿，不写入")
    p.add_argument("--draft-id", required=True)
    p.add_argument("--changes", required=True)
    p.add_argument("--today", default="")

    p = sub.add_parser("confirm_add", aliases=["confirm"], help="确认后追加写入金山文档")
    p.add_argument("--draft-id", required=True)
    p.add_argument("--backend", choices=["mcporter", "mock"], default="mcporter")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_FILE), help="配置文件，默认 data/config.json；不存在时使用内置链接解析")
    p.add_argument("--mock-file", default="", help="mock backend JSON file")

    p = sub.add_parser("cancel_draft", aliases=["cancel"], help="取消草稿，不写入")
    p.add_argument("--draft-id", required=True)
    return parser


def store_from_args(args: argparse.Namespace) -> DraftStore:
    return DraftStore(Path(args.state_file).expanduser() if args.state_file else None)


def cmd_parse(args: argparse.Namespace) -> int:
    draft = parse_item(args.text, today=parse_iso_date(args.today))
    store_from_args(args).put(draft)
    print(render_draft(draft))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    store = store_from_args(args)
    draft = store.get(args.draft_id)
    if draft.get("status") == "written":
        print("该事项已写入，是否需要新增一条相似事项？")
        return 0
    if draft.get("status") == "cancelled":
        print("该草稿已取消，不能继续修改。")
        return 1
    draft = update_draft(draft, args.changes, today=parse_iso_date(args.today))
    store.put(draft)
    print(render_draft(draft))
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    store = store_from_args(args)
    draft = store.get(args.draft_id)
    if draft.get("status") == "written":
        print("该事项已写入，是否需要新增一条相似事项？")
        return 0
    if draft.get("status") == "cancelled":
        print("该草稿已取消，未写入金山文档。")
        return 1

    try:
        backend, max_scan_rows, header_row = backend_from_args(
            args.backend, config_path=args.config or None, mock_file=args.mock_file or None
        )
        result = KDocsClient(backend, max_scan_rows=max_scan_rows, header_row=header_row).add_item(draft)
    except KDocsError as exc:
        print(f"写入失败：{exc}")
        print("")
        print("tab 分隔备用行：")
        print(tab_row(draft))
        return 1

    draft = store.mark_written(args.draft_id, result.number, result.row_number)
    fields = draft.get("fields") or {}
    print("已写入事项总表：")
    print(f"编号：{result.number}")
    print(f"行号：第 {result.row_number} 行")
    print(f"项目名称：{fields.get('项目名称', '')}")
    print(f"事项描述：{fields.get('事项描述', '')}")
    print(f"下一步动作：{fields.get('下一步动作', '')}")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    store_from_args(args).cancel(args.draft_id)
    print("已取消当前草稿，未写入金山文档。")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.action in ("parse_item", "parse"):
            return cmd_parse(args)
        if args.action in ("update_draft", "update"):
            return cmd_update(args)
        if args.action in ("confirm_add", "confirm"):
            return cmd_confirm(args)
        if args.action in ("cancel_draft", "cancel"):
            return cmd_cancel(args)
    except (ValueError, StateError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.error(f"unknown action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
