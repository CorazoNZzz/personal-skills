#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class StateError(RuntimeError):
    pass


def default_state_file() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "drafts.json"


class DraftStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or default_state_file())

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"drafts": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise StateError(f"cannot read draft state: {exc}") from exc
        if not isinstance(data, dict):
            raise StateError("draft state must be a JSON object")
        data.setdefault("drafts", {})
        return data

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def put(self, draft: Dict[str, Any]) -> None:
        draft_id = str(draft.get("draft_id") or "")
        if not draft_id:
            raise StateError("draft_id is required")
        data = self.load()
        data["drafts"][draft_id] = draft
        self.save(data)

    def get(self, draft_id: str) -> Dict[str, Any]:
        data = self.load()
        draft = data.get("drafts", {}).get(draft_id)
        if not isinstance(draft, dict):
            raise StateError(f"draft not found: {draft_id}")
        return draft

    def mark_written(self, draft_id: str, number: str, row_number: int) -> Dict[str, Any]:
        data = self.load()
        draft = data.get("drafts", {}).get(draft_id)
        if not isinstance(draft, dict):
            raise StateError(f"draft not found: {draft_id}")
        draft["status"] = "written"
        draft["written_number"] = number
        draft["written_row"] = row_number
        draft.setdefault("fields", {})["编号"] = number
        self.save(data)
        return draft

    def cancel(self, draft_id: str) -> Dict[str, Any]:
        data = self.load()
        draft = data.get("drafts", {}).get(draft_id)
        if not isinstance(draft, dict):
            raise StateError(f"draft not found: {draft_id}")
        draft["status"] = "cancelled"
        self.save(data)
        return draft
