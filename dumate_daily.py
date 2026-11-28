#!/usr/bin/env python3
"""Baidu DuMate daily login bonus runner.

Credentials:
    DUMATE_COOKIES
        One account per line. Each line may be prefixed with "label|".
        The cookie value must come from a console.bce.baidu.com request and
        include bce-sessionid. bce-user-info is required when claiming.
    DUMATE_COOKIE
        Single-account fallback when DUMATE_COOKIES is empty.

The script reads the pre-claim state, submits the login bonus only when it is
available, then verifies both hasIssued and the positive totalPoints delta.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote_plus

import requests


PROVIDER = "dumate"
DEFAULT_BASE_URL = "https://console.bce.baidu.com"
BASE_URL_ENV = "DUMATE_BASE_URL"
COOKIES_ENV = "DUMATE_COOKIES"
COOKIE_ENV = "DUMATE_COOKIE"
COOKIE_FILE_ENV = "DUMATE_COOKIE_FILE"
NOTIFY_ENV = "DUMATE_NOTIFY"
NOTIFY_POLICY_ENV = "DUMATE_NOTIFY_POLICY"

LOGIN_BONUS_INFO_PATH = "/api/dumate/points/loginBonusInfo"
LOGIN_BONUS_CLAIM_PATH = "/api/dumate/points/loginBonus"
QUOTA_OVERVIEW_PATH = (
    "/api/dumate/points/quota_overview"
    "?timezone=Asia%2FShanghai&clientType=desktop&ignoreLoginBonus=true"
)
USER_INFO_PATH = "/api/dumate/user/info"

REQUEST_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "DuMate/1.0.82 Chrome/130.0.0.0 Electron/33.0.0 Safari/537.36"
)


class ConfigError(ValueError):
    """Configuration or credential input error."""


class APIError(RuntimeError):
    """Classified request failure."""

    def __init__(
        self,
        result: str,
        message: str,
        *,
        http_status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class CookieValue:
    name: str
    value: str


def emit(payload: Mapping[str, Any]) -> None:
    """Write one machine-readable JSON line."""
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        flush=True,
    )


def _redact(value: Any, secrets: Sequence[str]) -> str:
    text = str(value)
    unique: list[str] = []
    for secret in secrets:
        secret = str(secret or "")
        if secret and secret not in unique:
            unique.append(secret)
    for secret in sorted(unique, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def _safe_label(raw: str, index: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "account_%d" % index
    if re.fullmatch(r"1\d{10}", text):
        return text[:3] + "****" + text[-4:]
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
        local, domain = text.split("@", 1)
        return (local[:1] or "*") + "***@" + domain
    if len(text) > 64:
        text = text[:61] + "..."
    return text


def _split_cookie_pairs(raw: str) -> list[CookieValue]:
    """Parse a Cookie header while respecting quoted semicolons."""
    pairs: list[CookieValue] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for char in str(raw or ""):
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quoted:
            current.append(char)
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
            current.append(char)
            continue
        if char == ";" and not quoted:
            part = "".join(current).strip()
            current = []
            if part:
                pairs.append(_parse_cookie_pair(part))
            continue
        current.append(char)
    part = "".join(current).strip()
    if part:
        pairs.append(_parse_cookie_pair(part))

    deduplicated: dict[str, CookieValue] = {}
    for item in pairs:
        deduplicated[item.name] = item
    return list(deduplicated.values())


def _parse_cookie_pair(part: str) -> CookieValue:
    if "=" not in part:
        raise ConfigError("cookie contains a segment without '='")
    name, value = part.split("=", 1)
    name = name.strip()
    value = value.strip()
    if not name:
        raise ConfigError("cookie contains an empty name")
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]
    if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
        raise ConfigError("cookie contains a newline")
    return CookieValue(name=name, value=value)


def parse_cookie(raw: str) -> list[CookieValue]:
    """Parse and validate one account cookie."""
    text = str(raw or "").strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    cookies = _split_cookie_pairs(text)
    if not cookies:
        raise ConfigError("cookie is empty")
    names = {item.name for item in cookies}
    if "bce-sessionid" not in names:
        raise ConfigError("cookie is missing bce-sessionid")
    return cookies


def cookie_header(cookies: Sequence[CookieValue]) -> str:
    """Serialize cookies using DuMate's quoting rules."""
    rendered: list[str] = []
    for item in cookies:
        value = item.value
        if re.search(r"[:|;=\s]", value):
            value = '"' + value.replace('"', '\\"') + '"'
        rendered.append(item.name + "=" + value)
    return "; ".join(rendered)


def csrf_token(cookies: Sequence[CookieValue]) -> str:
    for item in cookies:
        if item.name == "bce-user-info":
            return item.value
    return ""


def load_accounts(
    env: Optional[Mapping[str, str]] = None,
) -> list[dict[str, Any]]:
    """Load isolated accounts without printing credential values."""
    values = os.environ if env is None else env
    raw = str(values.get(COOKIES_ENV, "") or "").strip()
    if not raw:
        raw = str(values.get(COOKIE_ENV, "") or "").strip()
    if not raw:
        configured_path = str(values.get(COOKIE_FILE_ENV, "") or "").strip()
        path = (
            configured_path
            if configured_path
            else os.path.join(os.path.expanduser("~"), ".dumate-cookies")
        )
        if configured_path or os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    raw = handle.read().strip()
            except OSError as exc:
                raise ConfigError("cannot read DUMATE_COOKIE_FILE: %s" % exc) from exc
            if raw.upper().startswith(COOKIES_ENV + "="):
                raw = raw.split("=", 1)[1].strip()
    if not raw:
        raise ConfigError(
            "DUMATE_COOKIES, DUMATE_COOKIE, or DUMATE_COOKIE_FILE is not configured"
        )

    if "\n" in raw or "\r" in raw:
        parts = re.split(r"[\r\n]+", raw)
    else:
        parts = re.split(r"\s+&\s+", raw)
    parts = [part.strip() for part in parts if part.strip()]
    if not parts:
        raise ConfigError("no accounts found in DUMATE_COOKIES")

    accounts: list[dict[str, Any]] = []
    for index, part in enumerate(parts, 1):
        label = "account_%d" % index
        cookie_text = part
        if "|" in part:
            possible_label, possible_cookie = part.split("|", 1)
            if possible_cookie.strip():
                label = _safe_label(possible_label, index)
                cookie_text = possible_cookie.strip()
        try:
            cookies = parse_cookie(cookie_text)
        except ConfigError as exc:
            raise ConfigError("account %d: %s" % (index, exc)) from exc
        accounts.append(
            {
                "note": label,
                "cookies": cookies,
                "cookie_header": cookie_header(cookies),
                "csrf": csrf_token(cookies),
            }
        )
    return accounts


def _normalize_base_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text.startswith("https://") and not text.startswith("http://"):
        raise ConfigError("DUMATE_BASE_URL must be an http(s) URL")
    return text


def resolve_base_url(env: Optional[Mapping[str, str]] = None) -> str:
    values = os.environ if env is None else env
    return _normalize_base_url(values.get(BASE_URL_ENV, DEFAULT_BASE_URL))


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
    )
    return session


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if text:
        return str(text)
    try:
        return json.dumps(response.json(), ensure_ascii=False)
    except Exception:
        return ""


def _looks_like_login_html(text: str) -> bool:
    head = str(text or "")[:1000].lower()
    return any(
        marker in head
        for marker in (
            "<!doctype html",
            "<html",
            "登录",
            "login.bce.baidu.com",
        )
    )


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    secrets: Sequence[str],
    json_body: Optional[Mapping[str, Any]] = None,
) -> tuple[Any, int]:
    try:
        if method == "GET":
            response = session.get(
                url,
                headers=dict(headers),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        else:
            response = session.post(
                url,
                headers=dict(headers),
                json=dict(json_body or {}),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
    except requests.RequestException as exc:
        raise APIError(
            "NETWORK_ERROR",
            "network request failed: %s" % _redact(exc, secrets),
        ) from exc
    except Exception as exc:
        raise APIError(
            "NETWORK_ERROR",
            "network request failed: %s" % _redact(exc, secrets),
        ) from exc

    status_code = int(getattr(response, "status_code", 0) or 0)
    text = _response_text(response)
    if 300 <= status_code < 400:
        location = ""
        headers_obj = getattr(response, "headers", {}) or {}
        try:
            location = str(headers_obj.get("Location", "") or "")
        except Exception:
            location = ""
        if "login" in location.lower():
            raise APIError(
                "AUTH_EXPIRED",
                "login session expired (HTTP %d redirect)" % status_code,
                http_status=status_code,
            )
        raise APIError(
            "REDIRECT",
            "request was redirected (HTTP %d)" % status_code,
            http_status=status_code,
        )
    if status_code in (401, 403):
        raise APIError(
            "AUTH_EXPIRED",
            "login session is invalid or expired (HTTP %d)" % status_code,
            http_status=status_code,
        )
    if status_code == 429:
        raise APIError(
            "RATE_LIMITED",
            "request was rate limited (HTTP %d)" % status_code,
            http_status=status_code,
        )
    if not 200 <= status_code < 300:
        raise APIError(
            "HTTP_ERROR",
            "request failed (HTTP %d)" % status_code,
            http_status=status_code,
        )

    content_type = ""
    headers_obj = getattr(response, "headers", {}) or {}
    try:
        content_type = str(headers_obj.get("Content-Type", "") or "").lower()
    except Exception:
        content_type = ""
    if "text/html" in content_type or _looks_like_login_html(text):
        raise APIError(
            "AUTH_EXPIRED",
            "login session expired; server returned a login page",
            http_status=status_code,
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise APIError(
            "INVALID_JSON",
            "response is not JSON: %s" % _redact(exc, secrets),
            http_status=status_code,
        ) from exc
    if not isinstance(payload, Mapping):
        raise APIError(
            "INVALID_RESPONSE",
            "response is not a JSON object",
            http_status=status_code,
        )

    message = str(
        payload.get("message")
        or payload.get("msg")
        or payload.get("detail")
        or ""
    )
    code = payload.get("code")
    failed = payload.get("success") is False
    if code not in (None, 0, "0") or failed:
        if re.search(r"登录|重新登录|login|expired", message, re.IGNORECASE):
            raise APIError(
                "AUTH_EXPIRED",
                _redact(message or "login session expired", secrets),
                http_status=status_code,
            )
        detail = message or "code=%s" % code
        raise APIError(
            "BUSINESS_ERROR",
            _redact(detail, secrets),
            http_status=status_code,
        )
    return payload.get("result"), status_code


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else number


def _truthy(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y"):
        return True
    if text in ("false", "0", "no", "n"):
        return False
    return None


def parse_bonus_info(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise APIError("STATUS_UNRECOGNIZED", "loginBonusInfo result is missing")
    issued = _truthy(payload.get("hasIssued"))
    points = _number(payload.get("totalPoints"))
    if issued is None:
        raise APIError(
            "STATUS_UNRECOGNIZED",
            "loginBonusInfo does not contain a boolean hasIssued",
        )
    if points is None:
        raise APIError(
            "STATUS_UNRECOGNIZED",
            "loginBonusInfo does not contain a numeric totalPoints",
        )
    times = _number(payload.get("totalTimes"))
    return {
        "has_issued": issued,
        "bonus_points": points,
        "total_times": int(times) if times is not None else None,
    }


def parse_quota(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    total = _number(payload.get("totalPoints"))
    used = _number(payload.get("usedPoints"))
    if total is None or used is None:
        return {}
    remaining = total - used
    if isinstance(remaining, float) and remaining.is_integer():
        remaining = int(remaining)
    return {
        "quota_total": total,
        "quota_used": used,
        "quota_remaining": remaining,
    }


def _headers(
    account: Mapping[str, Any],
    *,
    base_url: str,
    post: bool,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Referer": base_url + "/",
        "Cookie": str(account["cookie_header"]),
    }
    if post:
        csrf = str(account.get("csrf", "") or "")
        if not csrf:
            raise ConfigError(
                "cookie is missing bce-user-info, required as the csrftoken"
            )
        headers.update(
            {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": base_url,
                "csrftoken": csrf,
            }
        )
    return headers


def _read_bonus_info(
    session: requests.Session,
    base_url: str,
    account: Mapping[str, Any],
    secrets: Sequence[str],
) -> tuple[dict[str, Any], int]:
    payload, status = _request_json(
        session,
        "GET",
        base_url + LOGIN_BONUS_INFO_PATH,
        headers=_headers(account, base_url=base_url, post=False),
        secrets=secrets,
    )
    return parse_bonus_info(payload), status


def _read_quota(
    session: requests.Session,
    base_url: str,
    account: Mapping[str, Any],
    secrets: Sequence[str],
) -> tuple[dict[str, Any], Optional[int], Optional[str]]:
    try:
        payload, status = _request_json(
            session,
            "GET",
            base_url + QUOTA_OVERVIEW_PATH,
            headers=_headers(account, base_url=base_url, post=False),
            secrets=secrets,
        )
        return parse_quota(payload), status, None
    except APIError as exc:
        return {}, exc.http_status, exc.message


def _result(
    account: Mapping[str, Any],
    result: str,
    ok: bool,
    message: str,
    *,
    http_status: Optional[int] = None,
    claimed: bool = False,
    before: Optional[Mapping[str, Any]] = None,
    after: Optional[Mapping[str, Any]] = None,
    credit: Optional[float] = None,
    quota: Optional[Mapping[str, Any]] = None,
    quota_error: Optional[str] = None,
) -> dict[str, Any]:
    before = before or {}
    after = after or {}
    payload: dict[str, Any] = {
        "account": str(account.get("note", "account")),
        "provider": PROVIDER,
        "result": result,
        "ok": ok,
        "message": message,
        "http_status": http_status,
        "claimed": claimed,
        "before_has_issued": before.get("has_issued"),
        "after_has_issued": after.get("has_issued"),
        "bonus_points_before": before.get("bonus_points"),
        "bonus_points_after": after.get("bonus_points"),
        "credit": credit,
        "total_times": (after or before).get("total_times"),
    }
    if quota:
        payload.update(dict(quota))
    if quota_error:
        payload["quota_error"] = quota_error
    return payload


# ---------------------------------------------------------------------------
# Booster plan (growth plan): finish tasks -> draw -> claim physical prizes
#
# Endpoints come from the official web bundle (api/dumate/activity/growth-plan/*).
# The front-end gates a report behind task evidence: a task carrying ``query``
# only reports when the current artifact matches it, and ``SUITE`` tasks need
# the matching suite. The server still has the final say, so a rejected report
# is surfaced as a per-task failure instead of being treated as done.
# ---------------------------------------------------------------------------

PAGE_STATUS_PATH = "/api/dumate/activity/growth-plan/page/status"
BOOSTER_TASKS_PATH = "/api/dumate/activity/growth-plan/tasks"
COMPLETE_TASK_PATH = "/api/dumate/activity/growth-plan/task/complete"
DRAW_STATUS_PATH = "/api/dumate/activity/growth-plan/draw/status"
DRAW_PATH = "/api/dumate/activity/growth-plan/draw"
CLAIM_PRIZE_PATH = "/api/dumate/activity/growth-plan/prize/claim"

DEFAULT_CLIENT_VERSION = "1.0.82"
DEFAULT_DEVICE = "pc"

# Task types the front-end only reports after real evidence (query / suiteName)
# or after a real subscription state. They are still attempted, but flagged.
EVIDENCE_REQUIRED_TYPES = frozenset(
    {
        "CODE_MODE",
        "QUERY_INPUT",
        "USE_SKILL",
        "CREATE_SCHEDULED_TASK",
        "FIRST_CREATE_SCHEDULED_TASK",
        "SUITE",
        "MEDIA_SUITE_CREATION",
        "INVITATION",
        "INVITED",
        "FIRST_PRO_AUTO_RENEW",
        "PRO_AUTO_RENEW",
    }
)


def _pick(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return None


def _unwrap(payload: Any) -> Mapping[str, Any]:
    """Return the payload body, tolerating one extra ``result``/``data`` layer."""
    if not isinstance(payload, Mapping):
        raise APIError("BAD_PAYLOAD", "response is not a JSON object")
    for key in ("result", "data"):
        inner = payload.get(key)
        if isinstance(inner, Mapping) and len(payload) <= 3:
            return inner
    return payload


def _is_risk_message(message: str) -> bool:
    text = str(message or "").lower()
    return any(
        token in text
        for token in ("风控", "风险", "risk", "forbidden", "captcha", "验证", "频繁")
    )


def _check_business(body: Any, *, action: str) -> Mapping[str, Any]:
    """``_request_json`` already unwraps ``result`` and rejects the envelope.

    Some endpoints repeat ``success`` / ``code`` inside ``result``; honour those
    too, and translate a risk-control message into ``RISK_BLOCKED`` so a block
    is never mistaken for a completed task.
    """
    if not isinstance(body, Mapping):
        return {}
    message = str(body.get("message") or body.get("msg") or "")
    code = body.get("code")
    failed = body.get("success") is False or code not in (None, 0, "0", 200, "200")
    if not failed:
        return body
    if _is_risk_message(message):
        raise APIError("RISK_BLOCKED", "%s blocked by risk control: %s" % (action, message))
    raise APIError("BUSINESS_ERROR", "%s failed (code=%s): %s" % (action, code, message))


def parse_page_status(payload: Any) -> dict[str, Any]:
    body = _unwrap(payload)
    config = body.get("config") if isinstance(body.get("config"), Mapping) else {}
    return {
        "activity_id": _pick(body, "activity_id", "activityId"),
        "enabled": _pick(body, "enabled") is not False,
        "growth_plan_enable": _pick(body, "growth_plan_enable", "growthPlanEnable") is not False,
        "start_time": _pick(body, "start_time", "startTime"),
        "end_time": _pick(body, "end_time", "endTime"),
        "title": _pick(config, "title", "entry_title") if isinstance(config, Mapping) else None,
    }


def _normalize_task(item: Mapping[str, Any]) -> dict[str, Any]:
    completed = _number(_pick(item, "completed_count", "completedCount", "finished_count"))
    repeat = _number(_pick(item, "repeat_count", "repeatCount", "max_count"))
    finished_flag = _pick(item, "finished", "completed", "done")
    if completed is None:
        completed = 1.0 if finished_flag is True else 0.0
    if repeat is None or repeat <= 0:
        repeat = max(1.0, completed)
    query = _pick(item, "query")
    suite_name = _pick(item, "suite_name", "suiteName")
    return {
        "task_id": str(_pick(item, "task_id", "taskId") or ""),
        "task_name": _pick(item, "task_name", "taskName", "name"),
        "task_type": _pick(item, "task_type", "taskType"),
        "completed_count": int(completed),
        "repeat_count": int(repeat),
        "finished": completed >= repeat,
        "reward_points": _number(_pick(item, "reward_points", "rewardPoints", "points")),
        "jump_url": _pick(item, "jump_url", "jumpUrl"),
        "query": query,
        "suite_name": suite_name,
        "needs_evidence": bool(query or suite_name),
    }


def parse_tasks(payload: Any) -> list[dict[str, Any]]:
    body = _unwrap(payload)
    raw = _pick(body, "tasks", "task_list", "list", "groups", "modules") or []
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    tasks: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, Sequence) else []:
        if not isinstance(item, Mapping):
            continue
        nested = item.get("tasks")
        if isinstance(nested, Sequence):
            for sub in nested:
                if isinstance(sub, Mapping):
                    tasks.append(_normalize_task(sub))
            continue
        tasks.append(_normalize_task(item))
    return [task for task in tasks if task["task_id"]]


def parse_draw_status(payload: Any) -> dict[str, Any]:
    body = _unwrap(payload)
    remaining = _number(_pick(body, "remaining_draws", "remainingDraws", "remaining"))
    return {
        "remaining_draws": int(remaining) if remaining is not None else 0,
        "prizes": _pick(body, "prizes") or [],
        "my_prizes": _pick(body, "my_prizes", "myPrizes") or [],
        "winning_records": _pick(body, "winning_records", "winningRecords") or [],
    }


def parse_draw_result(payload: Any) -> dict[str, Any]:
    body = _unwrap(payload)
    return {
        "draw_record_id": _pick(body, "draw_record_id", "drawRecordId", "record_id", "recordId"),
        "prize_name": _pick(body, "prize_name", "prizeName", "name"),
        "prize_type": _pick(body, "prize_type", "prizeType", "type"),
        "need_contact": bool(_pick(body, "need_contact", "needContact")),
    }


def _activity_call(
    session: requests.Session,
    base_url: str,
    account: Mapping[str, Any],
    *,
    method: str,
    path: str,
    body: Optional[Mapping[str, Any]] = None,
    extra_headers: Optional[Mapping[str, str]] = None,
    secrets: Sequence[str],
) -> Any:
    headers = _headers(account, base_url=base_url, post=method != "GET")
    if extra_headers:
        headers.update({str(key): str(value) for key, value in extra_headers.items()})
    try:
        payload, _status = _request_json(
            session,
            method,
            base_url + path,
            headers=headers,
            secrets=secrets,
            json_body=body if method != "GET" else None,
        )
    except APIError as exc:
        if exc.result == "BUSINESS_ERROR" and _is_risk_message(exc.message):
            raise APIError("RISK_BLOCKED", exc.message) from None
        raise
    return payload


def fetch_page_status(session, base_url, account, secrets) -> dict[str, Any]:
    return parse_page_status(
        _activity_call(
            session, base_url, account, method="GET", path=PAGE_STATUS_PATH, secrets=secrets
        )
    )


def fetch_booster_tasks(
    session,
    base_url,
    account,
    secrets,
    *,
    device: str = DEFAULT_DEVICE,
    version: str = DEFAULT_CLIENT_VERSION,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {}
    if device:
        body["device"] = device
    if version:
        body["version"] = version
    payload = _activity_call(
        session,
        base_url,
        account,
        method="POST",
        path=BOOSTER_TASKS_PATH,
        body=body,
        secrets=secrets,
    )
    _check_business(payload, action="list booster tasks")
    return parse_tasks(payload)


def complete_booster_task(
    session, base_url, account, secrets, task_id: str
) -> dict[str, Any]:
    payload = _activity_call(
        session,
        base_url,
        account,
        method="POST",
        path=COMPLETE_TASK_PATH,
        body={"task_id": str(task_id)},
        secrets=secrets,
    )
    _check_business(payload, action="complete task %s" % task_id)
    body = _unwrap(payload)
    reward = _number(_pick(body, "reward_count", "rewardCount", "reward"))
    return {
        "task_id": str(task_id),
        "reward_count": int(reward) if reward is not None else None,
        "message": payload.get("message") if isinstance(payload, Mapping) else None,
    }


def fetch_draw_status(session, base_url, account, secrets) -> dict[str, Any]:
    payload = _activity_call(
        session, base_url, account, method="GET", path=DRAW_STATUS_PATH, secrets=secrets
    )
    _check_business(payload, action="draw status")
    return parse_draw_status(payload)


def draw_once(session, base_url, account, secrets) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    payload = _activity_call(
        session,
        base_url,
        account,
        method="POST",
        path=DRAW_PATH,
        body={},
        extra_headers={"X-Bce-Request-Id": request_id},
        secrets=secrets,
    )
    _check_business(payload, action="draw")
    result = parse_draw_result(payload)
    result["request_id"] = request_id
    return result


def claim_prize(
    session, base_url, account, secrets, *, draw_record_id: Any, contact: str
) -> bool:
    payload = _activity_call(
        session,
        base_url,
        account,
        method="POST",
        path=CLAIM_PRIZE_PATH,
        body={"draw_record_id": draw_record_id, "contact": contact},
        secrets=secrets,
    )
    _check_business(payload, action="claim prize")
    return True


def run_booster(
    session,
    base_url: str,
    account: Mapping[str, Any],
    secrets: Sequence[str],
    *,
    dry_run: bool = False,
    do_draw: bool = True,
    max_draw: int = 0,
    contact: str = "",
    only_tasks: Sequence[str] = (),
    device: str = DEFAULT_DEVICE,
    version: str = DEFAULT_CLIENT_VERSION,
) -> dict[str, Any]:
    """Run the booster plan for one account; never raises, reports instead."""
    outcome: dict[str, Any] = {
        "ok": False,
        "error": None,
        "page": None,
        "tasks_before": [],
        "completed": [],
        "tasks_failed": [],
        "draw": {"available": 0, "done": 0, "prizes": [], "claimed": []},
    }
    try:
        page = fetch_page_status(session, base_url, account, secrets)
        outcome["page"] = page
        if not page.get("enabled") or not page.get("growth_plan_enable"):
            outcome.update(ok=True, note="booster plan is not active, skipped")
            return outcome

        tasks = fetch_booster_tasks(
            session, base_url, account, secrets, device=device, version=version
        )
        outcome["tasks_before"] = tasks
        wanted = {str(item).strip() for item in only_tasks if str(item).strip()}
        pending = [task for task in tasks if not task["finished"]]
        if wanted:
            pending = [
                task
                for task in pending
                if task["task_id"] in wanted or str(task.get("task_name") or "") in wanted
            ]
        if dry_run:
            outcome.update(ok=True, note="dry-run: booster reads only, nothing submitted")
            return outcome

        for task in pending:
            try:
                done = complete_booster_task(
                    session, base_url, account, secrets, task["task_id"]
                )
                outcome["completed"].append(
                    {
                        "task_id": done["task_id"],
                        "name": task.get("task_name"),
                        "reward_count": done["reward_count"],
                    }
                )
            except APIError as exc:
                outcome["tasks_failed"].append(
                    {
                        "task_id": task["task_id"],
                        "name": task.get("task_name"),
                        "code": exc.result,
                        "message": exc.message,
                    }
                )

        if do_draw:
            status = fetch_draw_status(session, base_url, account, secrets)
            remaining = int(status.get("remaining_draws") or 0)
            outcome["draw"]["available"] = remaining
            limit = remaining if max_draw <= 0 else min(remaining, int(max_draw))
            for _ in range(limit):
                try:
                    drawn = draw_once(session, base_url, account, secrets)
                except APIError as exc:
                    outcome["draw"]["prizes"].append(
                        {"error": exc.result, "message": exc.message}
                    )
                    break
                outcome["draw"]["done"] += 1
                outcome["draw"]["prizes"].append(drawn)
                if drawn.get("need_contact") and contact and drawn.get("draw_record_id"):
                    try:
                        claim_prize(
                            session,
                            base_url,
                            account,
                            secrets,
                            draw_record_id=drawn["draw_record_id"],
                            contact=contact,
                        )
                        outcome["draw"]["claimed"].append(drawn["draw_record_id"])
                    except APIError as exc:
                        outcome["draw"]["prizes"].append(
                            {"claim_error": exc.result, "message": exc.message}
                        )
            outcome["draw"]["after"] = (
                fetch_draw_status(session, base_url, account, secrets)
                if limit
                else status
            )

        outcome["ok"] = True
    except APIError as exc:
        outcome["error"] = {
            "code": exc.result,
            "message": exc.message,
            "http_status": exc.http_status,
        }
    except ConfigError as exc:
        outcome["error"] = {"code": "CONFIG_ERROR", "message": str(exc)}
    except Exception as exc:
        outcome["error"] = {
            "code": "UNEXPECTED_ERROR",
            "message": "unexpected error: %s" % _redact(exc, secrets),
        }
    return outcome


def booster_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate booster counters across accounts."""
    outcomes = [result.get("booster") for result in results if isinstance(result.get("booster"), Mapping)]
    return {
        "accounts": len(outcomes),
        "tasks_completed": sum(len(item.get("completed") or []) for item in outcomes),
        "tasks_failed": sum(len(item.get("tasks_failed") or []) for item in outcomes),
        "draws_done": sum(int((item.get("draw") or {}).get("done") or 0) for item in outcomes),
    }

def _check_signin(
    account: Mapping[str, Any],
    *,
    mode: str = "claim",
    base_url: Optional[str] = None,
    session_factory: Callable[[], requests.Session] = make_session,
) -> dict[str, Any]:
    """Process one account without leaking its credentials."""
    try:
        resolved_base_url = _normalize_base_url(base_url or resolve_base_url())
    except ConfigError as exc:
        return _result(account, "CONFIG_ERROR", False, str(exc))

    secrets = [
        str(account.get("cookie_header", "")),
        str(account.get("csrf", "")),
    ]
    cookies = account.get("cookies", [])
    if isinstance(cookies, Iterable):
        for item in cookies:
            if isinstance(item, CookieValue):
                secrets.extend([item.value, item.name + "=" + item.value])

    if mode == "claim" and not str(account.get("csrf", "") or ""):
        return _result(
            account,
            "CREDENTIAL_INCOMPLETE",
            False,
            "cookie is missing bce-user-info, required as the csrftoken",
        )

    session = None
    try:
        session = session_factory()
        before, before_status = _read_bonus_info(
            session,
            resolved_base_url,
            account,
            secrets,
        )
        quota, _, quota_error = _read_quota(
            session,
            resolved_base_url,
            account,
            secrets,
        )
        if before["has_issued"]:
            return _result(
                account,
                "ALREADY_CLAIMED",
                True,
                "today's login bonus was already issued",
                http_status=before_status,
                claimed=True,
                before=before,
                after=before,
                quota=quota,
                quota_error=quota_error,
            )
        if mode == "query":
            return _result(
                account,
                "AVAILABLE",
                True,
                "today's login bonus is available",
                http_status=before_status,
                before=before,
                after=before,
                quota=quota,
                quota_error=quota_error,
            )

        _, claim_status = _request_json(
            session,
            "POST",
            resolved_base_url + LOGIN_BONUS_CLAIM_PATH,
            headers=_headers(
                account,
                base_url=resolved_base_url,
                post=True,
            ),
            secrets=secrets,
            json_body={},
        )
        after, after_status = _read_bonus_info(
            session,
            resolved_base_url,
            account,
            secrets,
        )
        quota, _, quota_error = _read_quota(
            session,
            resolved_base_url,
            account,
            secrets,
        )

        if not after["has_issued"]:
            return _result(
                account,
                "CLAIM_NOT_APPLIED",
                False,
                "claim request returned success but hasIssued is still false",
                http_status=after_status,
                before=before,
                after=after,
                quota=quota,
                quota_error=quota_error,
            )

        delta = _number(after["bonus_points"]) - _number(before["bonus_points"])
        if delta is None or delta <= 0:
            return _result(
                account,
                "CREDIT_UNCONFIRMED",
                False,
                "hasIssued is true, but totalPoints did not increase",
                http_status=after_status,
                before=before,
                after=after,
                quota=quota,
                quota_error=quota_error,
            )
        if isinstance(delta, float) and delta.is_integer():
            delta = int(delta)
        return _result(
            account,
            "CLAIMED",
            True,
            "login bonus confirmed by hasIssued and a positive points delta",
            http_status=after_status or claim_status,
            claimed=True,
            before=before,
            after=after,
            credit=delta,
            quota=quota,
            quota_error=quota_error,
        )
    except APIError as exc:
        return _result(
            account,
            exc.result,
            False,
            exc.message,
            http_status=exc.http_status,
        )
    except ConfigError as exc:
        return _result(account, "CONFIG_ERROR", False, str(exc))
    except Exception as exc:
        return _result(
            account,
            "UNEXPECTED_ERROR",
            False,
            "unexpected error: %s" % _redact(exc, secrets),
        )
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


def _account_secrets(account: Mapping[str, Any]) -> list[str]:
    """Credential values that must never appear in a message or a report."""
    secrets = [
        str(account.get("cookie_header", "")),
        str(account.get("csrf", "")),
    ]
    cookies = account.get("cookies", [])
    if isinstance(cookies, Iterable):
        for item in cookies:
            if isinstance(item, CookieValue):
                secrets.extend([item.value, item.name + "=" + item.value])
    return secrets


# Sign-in failures that make a booster attempt pointless (no usable session)
_BOOSTER_SKIP_RESULTS = frozenset({"CONFIG_ERROR", "CREDENTIAL_INCOMPLETE", "AUTH_EXPIRED"})


def check_account(
    account: Mapping[str, Any],
    *,
    mode: str = "claim",
    base_url: Optional[str] = None,
    session_factory: Callable[[], requests.Session] = make_session,
    booster: bool = True,
    booster_options: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Claim the login bonus, then optionally run the booster plan."""
    result = _check_signin(
        account,
        mode=mode,
        base_url=base_url,
        session_factory=session_factory,
    )
    options = dict(booster_options or {})
    if not booster:
        return result
    if mode == "query" and not options.get("booster_only"):
        return result
    if result.get("result") in _BOOSTER_SKIP_RESULTS:
        result["booster"] = {
            "ok": False,
            "skipped": True,
            "reason": "sign-in failed (%s), booster not attempted" % result.get("result"),
        }
        return result

    resolved_base_url = _normalize_base_url(base_url or resolve_base_url())
    secrets = _account_secrets(account)
    session = None
    try:
        session = session_factory()
        result["booster"] = run_booster(
            session,
            resolved_base_url,
            account,
            secrets,
            dry_run=bool(options.get("dry_run")),
            do_draw=bool(options.get("do_draw", True)),
            max_draw=int(options.get("max_draw") or 0),
            contact=str(options.get("contact") or ""),
            only_tasks=options.get("only_tasks") or (),
            device=str(options.get("device") or DEFAULT_DEVICE),
            version=str(options.get("version") or DEFAULT_CLIENT_VERSION),
        )
    except Exception as exc:
        result["booster"] = {
            "ok": False,
            "error": {"code": "UNEXPECTED_ERROR", "message": "unexpected error: %s" % _redact(exc, secrets)},
        }
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    return result


def run_accounts(
    accounts: Sequence[Mapping[str, Any]],
    *,
    mode: str = "claim",
    base_url: Optional[str] = None,
    session_factory: Callable[[], requests.Session] = make_session,
    output: Callable[[Mapping[str, Any]], None] = emit,
    booster: bool = True,
    booster_options: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for account in accounts:
        result = check_account(
            account,
            mode=mode,
            base_url=base_url,
            session_factory=session_factory,
            booster=booster,
            booster_options=booster_options,
        )
        results.append(result)
        output(result)
    return results


def build_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    success = sum(1 for result in results if result.get("ok") is True)
    return {
        "provider": PROVIDER,
        "accounts": len(results),
        "success": success,
        "failed": len(results) - success,
        "claimed_now": sum(
            1 for result in results if result.get("result") == "CLAIMED"
        ),
        "already_claimed": sum(
            1 for result in results if result.get("result") == "ALREADY_CLAIMED"
        ),
        "booster": booster_summary(results),
        "results": [dict(result) for result in results],
    }


def _notification_text(summary: Mapping[str, Any]) -> str:
    lines = [
        "DuMate Daily",
        "账号: %s  成功: %s  失败: %s"
        % (summary.get("accounts"), summary.get("success"), summary.get("failed")),
    ]
    for result in summary.get("results", []):
        credit = result.get("credit")
        suffix = " +%s" % credit if credit not in (None, "", 0) else ""
        lines.append(
            "%s: %s%s"
            % (result.get("account"), result.get("result"), suffix)
        )
    return "\n".join(lines)


def _post_notification(url: str, payload: Mapping[str, Any]) -> bool:
    try:
        response = requests.post(url, json=dict(payload), timeout=REQUEST_TIMEOUT)
        return 200 <= int(response.status_code) < 300
    except requests.RequestException:
        return False


def send_notifications(
    title: str,
    content: str,
    env: Optional[Mapping[str, str]] = None,
) -> list[str]:
    """Send to every configured channel; failures are returned, not raised."""
    values = os.environ if env is None else env
    failures: list[str] = []

    pushplus = str(values.get("PUSHPLUS_TOKEN", "") or "").strip()
    if pushplus:
        ok = _post_notification(
            "https://www.pushplus.plus/send",
            {
                "token": pushplus,
                "title": title,
                "content": content,
                "template": "txt",
            },
        )
        if not ok:
            failures.append("pushplus")

    bark = str(values.get("BARK_URL", "") or "").strip().rstrip("/")
    if bark:
        ok = _post_notification(
            bark,
            {"title": title, "body": content, "group": "DuMate Daily"},
        )
        if not ok:
            failures.append("bark")

    wx_token = str(values.get("WXPUSHER_APP_TOKEN", "") or "").strip()
    wx_uids = [
        item.strip()
        for item in re.split(r"[,;\s]+", values.get("WXPUSHER_UID", "") or "")
        if item.strip()
    ]
    if wx_token and wx_uids:
        ok = _post_notification(
            "https://wxpusher.zjiecode.com/api/send/message",
            {
                "appToken": wx_token,
                "content": content,
                "summary": title[:99],
                "contentType": 1,
                "uids": wx_uids,
            },
        )
        if not ok:
            failures.append("wxpusher")

    serverchan = str(values.get("SERVERCHAN_SENDKEY", "") or "").strip()
    if serverchan:
        url = "https://sctapi.ftqq.com/%s.send" % quote_plus(serverchan)
        ok = _post_notification(url, {"title": title, "desp": content})
        if not ok:
            failures.append("serverchan")

    wecom = str(values.get("WECOM_WEBHOOK", "") or "").strip()
    if wecom:
        ok = _post_notification(
            wecom,
            {"msgtype": "text", "text": {"content": title + "\n" + content}},
        )
        if not ok:
            failures.append("wecom")

    dingtalk = str(values.get("DINGTALK_WEBHOOK", "") or "").strip()
    if dingtalk:
        secret = str(values.get("DINGTALK_SECRET", "") or "").strip()
        if secret:
            timestamp = str(int(time.time() * 1000))
            signing = timestamp + "\n" + secret
            digest = hmac.new(
                secret.encode("utf-8"),
                signing.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            sign = quote_plus(base64.b64encode(digest).decode("utf-8"))
            separator = "&" if "?" in dingtalk else "?"
            dingtalk += separator + "timestamp=" + timestamp + "&sign=" + sign
        ok = _post_notification(
            dingtalk,
            {
                "msgtype": "text",
                "text": {"content": title + "\n" + content},
            },
        )
        if not ok:
            failures.append("dingtalk")

    generic = str(values.get("DUMATE_WEBHOOK_URL", "") or "").strip()
    if generic:
        ok = _post_notification(
            generic,
            {"title": title, "content": content, "provider": PROVIDER},
        )
        if not ok:
            failures.append("webhook")

    return failures


def maybe_notify(
    summary: Mapping[str, Any],
    *,
    env: Optional[Mapping[str, str]] = None,
    disabled: bool = False,
) -> None:
    if disabled:
        return
    values = os.environ if env is None else env
    if str(values.get(NOTIFY_ENV, "1") or "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return
    policy = str(values.get(NOTIFY_POLICY_ENV, "always") or "always").lower()
    if policy in ("fail-only", "fail_only", "failure") and not summary.get("failed"):
        return
    failures = send_notifications(
        "DuMate Daily",
        _notification_text(summary),
        env=values,
    )
    if failures:
        print(
            "notification failed: " + ", ".join(failures),
            file=sys.stderr,
            flush=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claim the DuMate daily login bonus with server-side readback."
    )
    parser.add_argument(
        "--query",
        "--status",
        action="store_true",
        dest="query",
        help="read status without claiming",
    )
    parser.add_argument(
        "--only",
        type=int,
        default=0,
        help="run only one 1-based account index",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="disable configured push channels for this run",
    )
    parser.add_argument(
        "--no-booster",
        action="store_true",
        help="skip the booster plan (tasks / draws) and only handle the login bonus",
    )
    parser.add_argument(
        "--booster-only",
        action="store_true",
        help="skip the login-bonus claim and run the booster plan only",
    )
    parser.add_argument(
        "--booster-dry-run",
        action="store_true",
        help="read booster status and tasks without submitting anything",
    )
    parser.add_argument(
        "--no-draw",
        action="store_true",
        help="complete booster tasks but do not draw",
    )
    parser.add_argument(
        "--max-draw",
        type=int,
        default=0,
        help="cap draws in this run (default: use the remaining draws reported by the server)",
    )
    parser.add_argument(
        "--contact",
        default="",
        help="contact info used to claim a physical prize",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        metavar="TASK_ID|NAME",
        help="only attempt these booster tasks (repeatable), useful to verify one by one",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("status",),
        help=argparse.SUPPRESS,
    )
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    session_factory: Callable[[], requests.Session] = make_session,
    output: Callable[[Mapping[str, Any]], None] = emit,
) -> int:
    args = build_parser().parse_args(argv)
    mode = "query" if args.query or args.action == "status" else "claim"
    if args.booster_only:
        mode = "query"
    booster_options = {
        "dry_run": bool(args.booster_dry_run),
        "do_draw": not args.no_draw,
        "max_draw": int(args.max_draw or 0),
        "contact": str(args.contact or ""),
        "only_tasks": list(args.task or []),
        "booster_only": bool(args.booster_only),
    }
    try:
        accounts = load_accounts(env)
        base_url = resolve_base_url(env)
        if args.only:
            if args.only < 1 or args.only > len(accounts):
                raise ConfigError("--only is outside the configured account range")
            accounts = [accounts[args.only - 1]]
    except ConfigError as exc:
        result = _result(
            {"note": "config"},
            "CONFIG_ERROR",
            False,
            str(exc),
        )
        summary = build_summary([result])
        output(result)
        output(summary)
        return 2

    results = run_accounts(
        accounts,
        mode=mode,
        base_url=base_url,
        session_factory=session_factory,
        output=output,
        booster=not args.no_booster,
        booster_options=booster_options,
    )
    summary = build_summary(results)
    output(summary)
    maybe_notify(
        summary,
        env=env,
        disabled=bool(args.no_notify),
    )
    return 0 if summary["failed"] == 0 else 1


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _configure_utf8_stdio()
    sys.exit(main())
