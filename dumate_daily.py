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


def check_account(
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


def run_accounts(
    accounts: Sequence[Mapping[str, Any]],
    *,
    mode: str = "claim",
    base_url: Optional[str] = None,
    session_factory: Callable[[], requests.Session] = make_session,
    output: Callable[[Mapping[str, Any]], None] = emit,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for account in accounts:
        result = check_account(
            account,
            mode=mode,
            base_url=base_url,
            session_factory=session_factory,
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
