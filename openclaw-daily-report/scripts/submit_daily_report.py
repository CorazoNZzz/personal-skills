#!/usr/bin/env python3
import argparse
import base64
import datetime as dt
import difflib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}


class ApiRequestError(Exception):
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        payload: Optional[Any] = None,
        raw_text: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.raw_text = raw_text


def iter_chrome_leveldb_files(profile: str = "Default") -> List[Path]:
    profile = profile or "Default"
    leveldb_dirs: List[Path] = []

    user_data_dir = os.environ.get("OPENCLAW_CHROME_USER_DATA_DIR") or os.environ.get("CHROME_USER_DATA_DIR")
    if user_data_dir:
        leveldb_dirs.append(Path(user_data_dir).expanduser() / profile / "Local Storage" / "leveldb")

    if sys.platform == "darwin":
        leveldb_dirs.append(
            Path.home()
            / "Library"
            / "Application Support"
            / "Google"
            / "Chrome"
            / profile
            / "Local Storage"
            / "leveldb"
        )
    elif sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            leveldb_dirs.append(
                Path(local_app_data)
                / "Google"
                / "Chrome"
                / "User Data"
                / profile
                / "Local Storage"
                / "leveldb"
            )
    else:
        leveldb_dirs.extend(
            [
                Path.home() / ".config" / "google-chrome" / profile / "Local Storage" / "leveldb",
                Path.home() / ".config" / "chromium" / profile / "Local Storage" / "leveldb",
            ]
        )

    leveldb = next((p for p in leveldb_dirs if p.exists()), None)
    if not leveldb:
        return []
    files = sorted(
        [p for p in leveldb.iterdir() if p.suffix in {".log", ".ldb"}],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files


def scan_file_for_jwts(file_path: Path, origin_hint: Optional[str]) -> List[Tuple[str, int]]:
    try:
        raw = file_path.read_bytes()
    except Exception:
        return []

    text = raw.decode("latin1", errors="ignore")
    found: List[Tuple[str, int]] = []
    for m in JWT_RE.finditer(text):
        token = m.group(0)
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        context = text[start:end].lower()
        score = 0
        if "token" in context:
            score += 3
        if "auth" in context or "bearer" in context:
            score += 2
        if origin_hint and origin_hint.lower() in context:
            score += 5
        found.append((token, score))
    return found


def get_unverified_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    # Parse JWT payload without signature verification, only for local candidate ranking/filtering.
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8"))
        if isinstance(payload, dict):
            return payload
        return None
    except Exception:
        return None


def get_unverified_jwt_exp(token: str) -> Optional[int]:
    payload = get_unverified_jwt_payload(token) or {}
    exp = payload.get("exp")
    try:
        return int(exp) if exp is not None else None
    except Exception:
        return None


def token_matches_expected_user(token: str, expected_user: Optional[str]) -> bool:
    if not expected_user:
        return True
    expected = str(expected_user).strip().lower()
    if not expected:
        return True
    payload = get_unverified_jwt_payload(token) or {}
    candidates: List[str] = []
    for key in ("username", "user_name", "name", "real_name", "sub"):
        value = payload.get(key)
        if value is None:
            continue
        candidates.append(str(value).strip().lower())
    return expected in candidates


def get_token_from_chrome(profile: str, origin_hint: Optional[str], expected_user: Optional[str] = None) -> Optional[str]:
    candidates: Dict[str, int] = {}
    for file_path in iter_chrome_leveldb_files(profile=profile):
        for token, score in scan_file_for_jwts(file_path, origin_hint):
            candidates[token] = max(candidates.get(token, -999), score)

    if not candidates:
        return None

    now_ts = int(time.time())
    enriched: List[Tuple[str, int, int, int, int]] = []  # token, score, is_valid, exp, is_match
    for token, score in candidates.items():
        exp = get_unverified_jwt_exp(token) or 0
        is_valid = 1 if exp > now_ts + 60 else 0
        is_match = 1 if token_matches_expected_user(token, expected_user) else 0
        enriched.append((token, score, is_valid, exp, is_match))

    valid_tokens = [t for t in enriched if t[2] == 1]
    target = valid_tokens if valid_tokens else enriched
    if expected_user:
        matched = [t for t in target if t[4] == 1]
        if matched:
            target = matched
        else:
            return None

    ranked = sorted(target, key=lambda x: (x[4], x[1], x[2], x[3], len(x[0])), reverse=True)
    return ranked[0][0]


def load_entries(entries_file: Path) -> List[Dict[str, Any]]:
    data = json.loads(entries_file.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("entries file must be a JSON array")
    # Field name alias: user-friendly names -> internal canonical names
    FIELD_ALIAS = {
        "project":          "project_name",
        "content":          "progress_content",
        "hours":            "work_hours",
        "risks":            "risks_issues",
    }
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each entry must be a JSON object")
        entry = dict(item)
        for alias, canonical in FIELD_ALIAS.items():
            if alias in entry and canonical not in entry:
                entry[canonical] = entry[alias]
        out.append(entry)
    return out


def normalize_hours(raw: Any) -> float:
    if raw is None or raw == "":
        return 0.0
    return float(raw)


def to_non_empty_text(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def normalize_project_name(name: str) -> str:
    # Normalize unicode width/forms first, then unify quote variants.
    s = unicodedata.normalize("NFKC", name).strip()
    quote_map = str.maketrans(
        {
            "“": '"',
            "”": '"',
            "„": '"',
            "‟": '"',
            "＂": '"',
            "‘": "'",
            "’": "'",
            "‚": "'",
            "‛": "'",
            "＇": "'",
            "「": '"',
            "」": '"',
            "『": '"',
            "』": '"',
            "《": "<",
            "》": ">",
            "〈": "<",
            "〉": ">",
        }
    )
    s = s.translate(quote_map)
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_phase_tokens(s: str) -> str:
    # Unify Chinese numerals in "X期" into Arabic digits.
    phase_map = {
        "一": "1",
        "二": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
        "十": "10",
    }

    def repl(m: re.Match) -> str:
        raw = m.group(1)
        return f"{phase_map.get(raw, raw)}期"

    return re.sub(r"([一二三四五六七八九十])期", repl, s)


def simplify_project_name(name: str) -> str:
    s = normalize_project_name(name).lower()
    s = normalize_phase_tokens(s)
    s = re.sub(r"[\"'<>（）()\[\]【】《》“”‘’\-_/、,，.。:：;；|]+", "", s)
    s = s.replace("项目", "")
    s = s.replace("工程", "")
    s = re.sub(r"\s+", "", s)
    return s


def build_tokens(s: str) -> List[str]:
    # Token strategy for spoken shorthand:
    # - phase token (e.g. 2期)
    # - alnum chunks
    # - Chinese chunks (2-6 chars)
    # - 2/3-char grams for Chinese chunks
    out: List[str] = []
    phase_tokens = re.findall(r"\d+期", s)
    out.extend(phase_tokens)

    out.extend(re.findall(r"[a-z0-9]{2,}", s))

    zh_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", s)
    for c in zh_chunks:
        out.append(c)
        if len(c) >= 2:
            for i in range(len(c) - 1):
                out.append(c[i : i + 2])
        if len(c) >= 3:
            for i in range(len(c) - 2):
                out.append(c[i : i + 3])

    # dedupe while keeping order
    seen = set()
    uniq = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def load_aliases_file(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    alias_path = Path(path)
    if not alias_path.exists():
        raise ValueError(f"aliases file not found: {path}")
    data = json.loads(alias_path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        return data
    raise ValueError("aliases file must be a JSON object: {\"别名\": 255 | \"正式项目名\"}")


def get_default_credentials_file() -> Path:
    # .../openclaw-daily-report/scripts/submit_daily_report.py -> .../openclaw-daily-report/.local-secrets.json
    return Path(__file__).resolve().parents[1] / ".local-secrets.json"


def load_local_credentials(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        return data
    raise ValueError("credentials file must be a JSON object")


def prepare_project_match_indexes(projects: List[Dict[str, Any]]) -> Dict[str, Any]:
    exact_name_to_id = {to_non_empty_text(p.get("project_name")): p.get("id") for p in projects}
    normalized_name_to_ids: Dict[str, List[int]] = {}
    simplified_name_to_ids: Dict[str, List[int]] = {}
    project_id_set = {int(p["id"]) for p in projects if p.get("id") is not None}
    metas: List[Dict[str, Any]] = []

    for p in projects:
        pid_raw = p.get("id")
        pname = to_non_empty_text(p.get("project_name"))
        if pid_raw is None or not pname:
            continue
        pid = int(pid_raw)
        norm = normalize_project_name(pname)
        simp = simplify_project_name(pname)
        toks = set(build_tokens(simp))

        normalized_name_to_ids.setdefault(norm, []).append(pid)
        simplified_name_to_ids.setdefault(simp, []).append(pid)
        metas.append(
            {
                "id": pid,
                "name": pname,
                "norm": norm,
                "simp": simp,
                "tokens": toks,
            }
        )

    return {
        "exact_name_to_id": exact_name_to_id,
        "normalized_name_to_ids": normalized_name_to_ids,
        "simplified_name_to_ids": simplified_name_to_ids,
        "project_id_set": project_id_set,
        "metas": metas,
    }


def resolve_alias_to_project_id(
    alias: str,
    alias_map_raw: Dict[str, Any],
    indexes: Dict[str, Any],
) -> Optional[int]:
    if not alias_map_raw:
        return None
    if alias not in alias_map_raw:
        return None
    target = alias_map_raw[alias]
    if isinstance(target, int):
        return target
    if isinstance(target, str):
        # treat as canonical project name
        exact = indexes["exact_name_to_id"].get(target)
        if exact is not None:
            return int(exact)
        # try normalized exact
        n = normalize_project_name(target)
        ids = indexes["normalized_name_to_ids"].get(n, [])
        if len(ids) == 1:
            return ids[0]
    return None


def smart_match_project_id(project_name: str, indexes: Dict[str, Any]) -> Tuple[Optional[int], str]:
    exact_name_to_id = indexes["exact_name_to_id"]
    normalized_name_to_ids = indexes["normalized_name_to_ids"]
    simplified_name_to_ids = indexes["simplified_name_to_ids"]
    metas = indexes["metas"]

    # 1) exact
    exact = exact_name_to_id.get(project_name)
    if exact is not None:
        return int(exact), "exact"

    # 2) normalized exact
    norm = normalize_project_name(project_name)
    n_ids = normalized_name_to_ids.get(norm, [])
    if len(n_ids) == 1:
        return n_ids[0], "normalized-exact"
    if len(n_ids) > 1:
        return None, "ambiguous-normalized-exact"

    # 3) simplified exact
    simp = simplify_project_name(project_name)
    if len(simp) >= 2:
        s_ids = simplified_name_to_ids.get(simp, [])
        if len(s_ids) == 1:
            return s_ids[0], "simplified-exact"
        if len(s_ids) > 1:
            return None, "ambiguous-simplified-exact"

    # 4) fuzzy ranking (voice shorthand friendly)
    if len(simp) < 2:
        return None, "too-short"

    entry_tokens = set(build_tokens(simp))
    scored: List[Tuple[int, int]] = []  # (score, project_id)
    for m in metas:
        score = 0
        ms = m["simp"]

        if simp and simp in ms:
            score = max(score, 80 + min(len(simp), 20))
        if ms and ms in simp:
            score = max(score, 65 + min(len(ms), 20))

        common_tokens = entry_tokens.intersection(m["tokens"])
        if common_tokens:
            token_score = len(common_tokens) * 8
            if any(t.endswith("期") for t in common_tokens):
                token_score += 12
            score = max(score, token_score)

        ratio = max(
            difflib.SequenceMatcher(None, simp, ms).ratio(),
            difflib.SequenceMatcher(None, norm, m["norm"]).ratio(),
        )
        score = max(score, int(ratio * 60))
        scored.append((score, m["id"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < 45:
        return None, "no-good-fuzzy-match"

    top_score, top_id = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -999
    if top_score - second_score <= 5:
        return None, "ambiguous-fuzzy-match"

    return top_id, "fuzzy"


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def read_password_from_env(env_name: str) -> str:
    value = os.environ.get(env_name, "")
    return value.strip()


def api_login(api_base: str, username: str, password: str, timeout: int = 30) -> str:
    url = f"{api_base.rstrip('/')}/v1/auth/login"
    try:
        resp = requests.post(
            url,
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise e

    try:
        payload = resp.json()
    except Exception:
        payload = None

    if resp.status_code >= 400:
        raise ApiRequestError(
            f"login failed [{resp.status_code}]",
            status_code=resp.status_code,
            payload=payload,
            raw_text=resp.text,
        )

    if not isinstance(payload, dict) or payload.get("code") not in (0, 200):
        raise ApiRequestError("login returned non-success code", status_code=resp.status_code, payload=payload)

    token = ((payload.get("data") or {}).get("access_token") or "").strip()
    if not token:
        raise ApiRequestError("login succeeded but access_token is empty", status_code=resp.status_code, payload=payload)
    return token


def is_auth_error(err: Exception) -> bool:
    if not isinstance(err, ApiRequestError):
        return False
    if err.status_code == 401:
        return True
    payload = err.payload
    if isinstance(payload, dict):
        code = payload.get("code")
        if code == 401:
            return True
        detail = str(payload.get("detail", "")).lower()
        message = str(payload.get("message", "")).lower()
        if "token" in detail or "token" in message:
            return True
        if "login" in detail or "login" in message:
            return True
    return False


def is_transient_error(err: Exception) -> bool:
    if isinstance(err, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(err, ApiRequestError) and err.status_code in TRANSIENT_HTTP_STATUS:
        return True
    return False


def try_refresh_token_from_chrome(
    current_token: str,
    chrome_profile: str,
    origin_hint: Optional[str],
    expected_user: Optional[str],
) -> Optional[str]:
    new_token = get_token_from_chrome(
        profile=chrome_profile,
        origin_hint=origin_hint,
        expected_user=expected_user,
    ) or ""
    if not new_token:
        return None
    if new_token == current_token:
        return None
    return new_token


def try_refresh_token_via_login(
    current_token: str,
    api_base: str,
    login_username: str,
    password_env: str,
    expected_user: Optional[str],
    failure_reasons: Optional[List[str]] = None,
) -> Optional[str]:
    username = (login_username or "").strip()
    if not username:
        if failure_reasons is not None:
            failure_reasons.append("login fallback skipped: missing login_username")
        return None
    password = read_password_from_env(password_env)
    if not password:
        if failure_reasons is not None:
            failure_reasons.append(f"login fallback skipped: missing password in {password_env}")
        return None
    new_token = api_login(api_base=api_base, username=username, password=password)
    if not new_token or new_token == current_token:
        if failure_reasons is not None:
            failure_reasons.append("login fallback did not return a new token")
        return None
    if expected_user and not token_matches_expected_user(new_token, expected_user):
        raise ValueError(
            f"login token identity mismatch. expected_user={expected_user}; "
            f"login_username={username}"
        )
    return new_token


def call_with_resilience(
    fn_name: str,
    fn,
    token: str,
    max_retries: int,
    retry_backoff_seconds: float,
    auto_refresh_token: bool,
    chrome_profile: str,
    origin_hint: Optional[str],
    expected_user: Optional[str],
    api_base: str,
    login_username: str,
    password_env: str,
):
    attempt = 0
    current_token = token
    refreshed_once = False

    while True:
        try:
            result = fn(current_token)
            return result, current_token
        except Exception as err:
            # 1) Auth failure: refresh token from Chrome and retry once.
            if auto_refresh_token and is_auth_error(err) and not refreshed_once:
                auth_refresh_failure_reasons: List[str] = []
                new_token = try_refresh_token_from_chrome(
                    current_token=current_token,
                    chrome_profile=chrome_profile,
                    origin_hint=origin_hint,
                    expected_user=expected_user,
                )
                if not new_token:
                    auth_refresh_failure_reasons.append("Chrome token refresh did not find a new usable token")
                if not new_token:
                    new_token = try_refresh_token_via_login(
                        current_token=current_token,
                        api_base=api_base,
                        login_username=login_username,
                        password_env=password_env,
                        expected_user=expected_user,
                        failure_reasons=auth_refresh_failure_reasons,
                    )
                if new_token:
                    refreshed_once = True
                    current_token = new_token
                    print(f"[retry] {fn_name}: token refreshed after auth failure", file=sys.stderr)
                    continue
                print(
                    f"ERROR: {fn_name}: API returned auth failure and token auto-refresh could not get a new token.",
                    file=sys.stderr,
                )
                print(
                    "  - If you expect to use Chrome token refresh, log in to the project management system in Chrome.",
                    file=sys.stderr,
                )
                print(
                    "  - If you expect to use login fallback, configure login_username and password in "
                    ".local-secrets.json.",
                    file=sys.stderr,
                )
                if auth_refresh_failure_reasons:
                    print("  Details:", file=sys.stderr)
                    for reason in auth_refresh_failure_reasons:
                        print(f"  - {reason}", file=sys.stderr)

            # 2) Transient failure: retry with backoff.
            if is_transient_error(err) and attempt < max_retries:
                attempt += 1
                sleep_seconds = retry_backoff_seconds * attempt
                print(
                    f"[retry] {fn_name}: transient error (attempt {attempt}/{max_retries}), "
                    f"sleep {sleep_seconds:.1f}s: {err}",
                    file=sys.stderr,
                )
                time.sleep(sleep_seconds)
                continue
            raise


def api_get_my_projects(api_base: str, token: str, timeout: int = 30) -> List[Dict[str, Any]]:
    url = f"{api_base.rstrip('/')}/v1/daily-reports/my-projects"
    try:
        resp = requests.get(url, headers=auth_headers(token), timeout=timeout)
    except requests.RequestException as e:
        raise e
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if resp.status_code >= 400:
        raise ApiRequestError(
            f"my-projects failed [{resp.status_code}]",
            status_code=resp.status_code,
            payload=payload,
            raw_text=resp.text,
        )
    if not isinstance(payload, dict) or payload.get("code") not in (0, 200):
        raise ApiRequestError("my-projects returned non-success code", status_code=resp.status_code, payload=payload)
    return payload.get("data") or []


def merge_other_entries(other_entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not other_entries:
        return None
    total_hours = 0.0
    progress_lines: List[str] = []
    risks_lines: List[str] = []
    for e in other_entries:
        total_hours += normalize_hours(e.get("work_hours"))
        p = to_non_empty_text(e.get("progress_content"))
        r = to_non_empty_text(e.get("risks_issues"))
        if p:
            progress_lines.append(p)
        if r:
            risks_lines.append(r)
    return {
        "project_id": None,
        "project_name": "学习或其他",
        "work_hours": round(total_hours, 2),
        "progress_content": "\n".join(progress_lines).strip(),
        "risks_issues": "\n".join(risks_lines).strip(),
    }


def build_batch_payload(
    entries: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    report_date: str,
    push_to: Optional[List[str]],
    alias_map_raw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    indexes = prepare_project_match_indexes(projects)
    project_id_set = indexes["project_id_set"]
    alias_map_raw = alias_map_raw or {}

    reports: List[Dict[str, Any]] = []
    other_candidates: List[Dict[str, Any]] = []
    errors: List[str] = []

    for idx, e in enumerate(entries, start=1):
        raw_project_id = e.get("project_id")
        project_name = to_non_empty_text(e.get("project_name"))
        work_hours = normalize_hours(e.get("work_hours"))
        progress_content = to_non_empty_text(e.get("progress_content"))
        risks_issues = to_non_empty_text(e.get("risks_issues"))

        has_hours = work_hours > 0
        has_progress = bool(progress_content)
        if has_hours != has_progress:
            errors.append(
                f"entry #{idx} [{project_name or 'UNKNOWN'}] requires both work_hours and progress_content"
            )
            continue
        if not has_hours and not has_progress:
            continue

        # Priority 1: explicit project_id from input
        project_id: Optional[int] = None
        if raw_project_id not in (None, "", "null"):
            try:
                candidate_id = int(raw_project_id)
            except Exception:
                errors.append(f"entry #{idx} has invalid project_id: {raw_project_id}")
                continue
            if candidate_id not in project_id_set:
                errors.append(f"entry #{idx} has unknown project_id: {candidate_id}")
                continue
            project_id = candidate_id

        # Priority 2: project_name exact/normalized matching
        if project_id is None and project_name:
            # Alias map has the highest priority for name-based matching.
            alias_id = resolve_alias_to_project_id(project_name, alias_map_raw, indexes)
            if alias_id is not None:
                if alias_id not in project_id_set:
                    errors.append(f"entry #{idx} alias resolves to unknown project_id: {alias_id}")
                    continue
                project_id = alias_id
            else:
                project_id, match_reason = smart_match_project_id(project_name, indexes)
                if project_id is None and match_reason.startswith("ambiguous"):
                    errors.append(
                        f"entry #{idx} ambiguous project_name: {project_name}; "
                        f"use project_id or alias file"
                    )
                    continue

        if project_id is None:
            other_candidates.append(
                {
                    "project_name": project_name or "学习或其他",
                    "work_hours": work_hours,
                    "progress_content": progress_content,
                    "risks_issues": risks_issues,
                }
            )
        else:
            reports.append(
                {
                    "project_id": int(project_id),
                    "work_hours": work_hours,
                    "progress_content": progress_content,
                    "risks_issues": risks_issues,
                }
            )

    if errors:
        raise ValueError("validation failed:\n" + "\n".join(errors))

    other_merged = merge_other_entries(other_candidates)
    if other_merged:
        reports.append(other_merged)

    if not reports:
        raise ValueError("no valid report entries")

    total_hours = round(sum(float(r["work_hours"]) for r in reports), 2)
    if total_hours < 8:
        raise ValueError(f"total work hours must be >= 8, got {total_hours}")

    return {
        "report_date": report_date,
        "push_to": push_to or [],
        "reports": reports,
    }


def api_submit_batch(api_base: str, token: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    url = f"{api_base.rstrip('/')}/v1/daily-reports/batch"
    headers = auth_headers(token)
    headers["Content-Type"] = "application/json"
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise e

    try:
        result = resp.json()
    except Exception:
        result = None

    if resp.status_code >= 400:
        raise ApiRequestError(
            f"submit failed [{resp.status_code}]",
            status_code=resp.status_code,
            payload=result,
            raw_text=resp.text,
        )
    if not isinstance(result, dict) or result.get("code") not in (0, 200):
        raise ApiRequestError("submit returned non-success code", status_code=resp.status_code, payload=result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and submit daily reports to /api/v1/daily-reports/batch"
    )
    parser.add_argument(
        "--api-base",
        default="",
        help="API base URL (e.g. http://127.0.0.1:8000/api). "
        "If omitted, load from credentials file key: api_base",
    )
    parser.add_argument("--entries-file", required=True, help="JSON array file of report entries")
    parser.add_argument("--report-date", default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--push-to", nargs="*", default=[], help="Optional employee names for push_to")
    parser.add_argument("--token", default="", help="JWT token; if omitted, auto-read from Chrome localStorage")
    parser.add_argument(
        "--expected-user",
        default="",
        help="Optional expected token user identity (matches JWT username/sub); prevents wrong-account submission",
    )
    parser.add_argument(
        "--login-username",
        default="",
        help="Optional API login username fallback when Chrome token is unavailable/expired",
    )
    parser.add_argument(
        "--credentials-file",
        default="",
        help="Optional local JSON credentials file; default auto-loads .local-secrets.json under skill root if exists",
    )
    parser.add_argument(
        "--password-env",
        default="OPENCLAW_DAILY_REPORT_PASSWORD",
        help="Environment variable name containing login password for --login-username",
    )
    parser.add_argument("--chrome-profile", default="Default", help="Chrome profile folder name")
    parser.add_argument(
        "--origin-hint",
        default="",
        help="Origin hint used when scanning localStorage LevelDB files; default derives from --api-base host",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print payload, do not submit")
    parser.add_argument("--show-token-source", action="store_true", help="Print how token was obtained")
    parser.add_argument("--max-retries", type=int, default=2, help="Max retries for transient API/network failures")
    parser.add_argument(
        "--retry-backoff-seconds",
        type=float,
        default=1.5,
        help="Backoff base seconds for retries (actual sleep = base * attempt)",
    )
    parser.add_argument(
        "--no-auto-token-refresh",
        action="store_true",
        help="Disable auto refresh token from Chrome when API returns auth failure",
    )
    parser.add_argument(
        "--project-aliases-file",
        default="",
        help="Optional JSON file mapping spoken aliases to project_id or canonical project_name",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    entries = load_entries(Path(args.entries_file))
    credentials_path: Optional[Path] = None
    if args.credentials_file:
        credentials_path = Path(args.credentials_file).expanduser()
    else:
        default_credentials = get_default_credentials_file()
        if default_credentials.exists():
            credentials_path = default_credentials
    credentials = load_local_credentials(credentials_path) if credentials_path else {}

    def get_cred_str(key: str) -> str:
        value = credentials.get(key)
        if value is None:
            return ""
        return str(value).strip()

    api_base = args.api_base.strip() or get_cred_str("api_base")
    if not api_base:
        print(
            "ERROR: api base is required. Provide --api-base or set api_base in --credentials-file "
            "(or .local-secrets.json).",
            file=sys.stderr,
        )
        return 2

    # CLI has highest priority. credentials file fills only missing values.
    token = args.token.strip() or get_cred_str("token")
    expected_user = args.expected_user.strip() or get_cred_str("expected_user")
    login_username = (args.login_username or "").strip() or get_cred_str("login_username")
    password_env = (
        (args.password_env or "").strip()
        or get_cred_str("password_env")
        or "OPENCLAW_DAILY_REPORT_PASSWORD"
    )
    if not os.environ.get(password_env, "").strip():
        cred_password = get_cred_str("password")
        if cred_password:
            os.environ[password_env] = cred_password

    derived_origin = (urlparse(api_base).hostname or "").strip()
    origin_hint = (
        (args.origin_hint or "").strip()
        or get_cred_str("origin_hint")
        or derived_origin
        or "localhost"
    )

    token_source = "arg --token"
    if args.token.strip():
        token_source = "arg --token"
    elif get_cred_str("token"):
        token_source = f"credentials file ({credentials_path})"
    if not token:
        token = get_token_from_chrome(
            profile=args.chrome_profile,
            origin_hint=origin_hint,
            expected_user=expected_user or None,
        ) or ""
        if token:
            token_source = f"chrome localStorage ({args.chrome_profile})"
        elif login_username:
            password = read_password_from_env(password_env)
            if password:
                token = api_login(api_base=api_base, username=login_username, password=password)
                token_source = f"/v1/auth/login ({login_username})"
    if not token:
        print(
            "ERROR: token not found. Use one of: --token, Chrome logged-in token, or "
            "--login-username with password in --password-env, or --credentials-file.",
            file=sys.stderr,
        )
        return 2

    if expected_user and not token_matches_expected_user(token, expected_user):
        print(
            f"ERROR: token identity mismatch. expected_user={expected_user}. "
            "Provide correct --token or switch Chrome account/profile.",
            file=sys.stderr,
        )
        return 2

    if args.show_token_source:
        print(f"token source: {token_source}")

    auto_refresh_token = not args.no_auto_token_refresh
    if args.max_retries < 0:
        raise ValueError("--max-retries must be >= 0")
    if args.retry_backoff_seconds < 0:
        raise ValueError("--retry-backoff-seconds must be >= 0")

    projects, token = call_with_resilience(
        fn_name="get-my-projects",
        fn=lambda t: api_get_my_projects(api_base=api_base, token=t),
        token=token,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        auto_refresh_token=auto_refresh_token,
        chrome_profile=args.chrome_profile,
        origin_hint=origin_hint,
        expected_user=expected_user or None,
        api_base=api_base,
        login_username=login_username,
        password_env=password_env,
    )
    alias_map_raw = load_aliases_file(args.project_aliases_file) if args.project_aliases_file else {}
    payload = build_batch_payload(
        entries=entries,
        projects=projects,
        report_date=args.report_date,
        push_to=args.push_to,
        alias_map_raw=alias_map_raw,
    )

    print("payload preview:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.dry_run:
        return 0

    result, token = call_with_resilience(
        fn_name="submit-batch",
        fn=lambda t: api_submit_batch(api_base=api_base, token=t, payload=payload),
        token=token,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        auto_refresh_token=auto_refresh_token,
        chrome_profile=args.chrome_profile,
        origin_hint=origin_hint,
        expected_user=expected_user or None,
        api_base=api_base,
        login_username=login_username,
        password_env=password_env,
    )
    print("submit result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
