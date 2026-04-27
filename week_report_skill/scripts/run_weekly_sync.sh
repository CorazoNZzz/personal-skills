#!/usr/bin/env bash
set -euo pipefail

# ---------- 参数 ----------
TARGET_ROW=0
PROJECT_NAME=""
PROJECT_COL=2
SCAN_ROW_FROM=3
SCAN_ROW_TO=200
START_DATE=""
END_DATE=""
NEXT_WEEK_PLAN=""
NEXT_WEEK_PLAN_FILE=""
APPLY_FLAG=""

usage() {
    echo "Usage: $0 [--target-row N] [--project-name NAME] [--project-col N]"
    echo "         [--scan-row-from N] [--scan-row-to N]"
    echo "         [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]"
    echo "         [--next-week-plan TEXT] [--next-week-plan-file FILE]"
    echo "         [--apply]"
    echo ""
    echo "  --target-row N        Row number of the weekly report sheet to sync"
    echo "  --project-name NAME   Project name (auto-search sheet rows if set)"
    echo "  --project-col N       Column containing project names (default: 2)"
    echo "  --scan-row-from N     First row to scan when searching by project name"
    echo "  --scan-row-to N       Last row to scan"
    echo "  --start-date YYYY-MM-DD  Weekly range start (default: this week's Monday)"
    echo "  --end-date YYYY-MM-DD    Weekly range end (default: this week's Friday)"
    echo "  --next-week-plan TEXT    Plan text for next week"
    echo "  --next-week-plan-file FILE  Read plan from file"
    echo "  --apply               Actually write changes (dry-run if omitted)"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-row)      TARGET_ROW="$2"; shift 2 ;;
        --project-name)    PROJECT_NAME="$2"; shift 2 ;;
        --project-col)     PROJECT_COL="$2"; shift 2 ;;
        --scan-row-from)   SCAN_ROW_FROM="$2"; shift 2 ;;
        --scan-row-to)     SCAN_ROW_TO="$2"; shift 2 ;;
        --start-date)      START_DATE="$2"; shift 2 ;;
        --end-date)        END_DATE="$2"; shift 2 ;;
        --next-week-plan)  NEXT_WEEK_PLAN="$2"; shift 2 ;;
        --next-week-plan-file) NEXT_WEEK_PLAN_FILE="$2"; shift 2 ;;
        --apply)           APPLY_FLAG="yes"; shift ;;
        -h|--help)         usage ;;
        *)                 echo "Unknown option: $1"; usage ;;
    esac
done

# ---------- 路径解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_FILE="$SCRIPT_DIR/mcporter_templates.example.json"

if [[ ! -f "$TEMPLATE_FILE" ]]; then
    echo "ERROR: Template file not found: $TEMPLATE_FILE" >&2
    exit 1
fi

if [[ "$TARGET_ROW" -le 0 && -z "$PROJECT_NAME" ]]; then
    echo "ERROR: Either --target-row or --project-name is required." >&2
    exit 1
fi

# ---------- 自动补全日期 ----------
if [[ -z "$START_DATE" || -z "$END_DATE" ]]; then
    # 计算本周一（假设周一为一周开始）
    today_day_of_week=$(date +%u)  # 1=Monday ... 7=Sunday
    monday_offset=$((today_day_of_week - 1))
    friday_offset=$((monday_offset + 4))

    monday=$(date -v-$((monday_offset))d +%Y-%m-%d 2>/dev/null || \
              python3 -c "from datetime import date, timedelta; d=date.today()-timedelta(days=$monday_offset); print(d.strftime('%Y-%m-%d'))")
    friday=$(date -v-$((friday_offset))d +%Y-%m-%d 2>/dev/null || \
             python3 -c "from datetime import date, timedelta; d=date.today()-timedelta(days=$friday_offset); print(d.strftime('%Y-%m-%d'))")

    [[ -z "$START_DATE" ]] && START_DATE="$monday"
    [[ -z "$END_DATE" ]]   && END_DATE="$friday"
fi

# ---------- 构建参数 ----------
PY_ARGS=(
    "$SCRIPT_DIR/sync_weekly_kdocs.py"
    --start-date "$START_DATE"
    --end-date "$END_DATE"
    --daily-archive-file "data/daily_records.jsonl"
    --backend "mcporter"
    --mcporter-template-file "$TEMPLATE_FILE"
    --confirm-range "YES"
)

if [[ "$TARGET_ROW" -gt 0 ]]; then
    PY_ARGS+=(--target-row "$TARGET_ROW")
fi

if [[ -n "$PROJECT_NAME" ]]; then
    PY_ARGS+=(--project-name "$PROJECT_NAME")
    PY_ARGS+=(--project-col "$PROJECT_COL")
    PY_ARGS+=(--scan-row-from "$SCAN_ROW_FROM")
    PY_ARGS+=(--scan-row-to "$SCAN_ROW_TO")
fi

if [[ -n "$NEXT_WEEK_PLAN_FILE" ]]; then
    PY_ARGS+=(--next-week-plan-file "$NEXT_WEEK_PLAN_FILE")
elif [[ -n "$NEXT_WEEK_PLAN" ]]; then
    PY_ARGS+=(--next-week-plan "$NEXT_WEEK_PLAN")
fi

if [[ "$APPLY_FLAG" == "yes" ]]; then
    PY_ARGS+=(--apply --confirm-write "WRITE")
fi

# ---------- 执行 ----------
cd "$SKILL_ROOT"
python3 "${PY_ARGS[@]}"
