#!/usr/bin/env python3
"""Read the local DuMate desktop session and write an ignored cookie file.

The desktop app stores an AES-256-GCM encrypted cookie array in auth.json.
This helper only reads those files. It never writes into the DuMate data
directory and never prints cookie or CSRF values.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from dumate_daily import (
    ConfigError,
    CookieValue,
    check_account,
    cookie_header,
    csrf_token,
)


TARGET_HOST = "console.bce.baidu.com"
DEFAULT_OUTPUT = Path.home() / ".dumate-cookies"


def desktop_user_data_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    values = os.environ if env is None else env
    override = str(values.get("DUMATE_USER_DATA_DIR", "") or "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(values.get("APPDATA", "") or Path.home()) / "qianfan-desktop-app"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "qianfan-desktop-app"
        )
    config_home = Path(
        values.get("XDG_CONFIG_HOME", "") or Path.home() / ".config"
    )
    return config_home / "qianfan-desktop-app"


def _domain_matches(domain: str, hostname: str) -> bool:
    value = str(domain or "").strip().lstrip(".").lower()
    hostname = hostname.lower()
    return bool(value) and (hostname == value or hostname.endswith("." + value))


def cookies_for_host(
    raw_cookies: Iterable[Mapping[str, Any]],
    hostname: str = TARGET_HOST,
) -> list[CookieValue]:
    selected: list[CookieValue] = []
    for item in raw_cookies:
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        domain = str(item.get("domain", "") or "").strip()
        if domain and not _domain_matches(domain, hostname):
            continue
        value = str(item.get("value", "") or "").replace("\r", "").replace("\n", "")
        selected.append(CookieValue(name=name, value=value))
    return selected


def decrypt_auth_file(
    auth_path: Path,
    key_path: Path,
) -> tuple[list[CookieValue], str]:
    if not auth_path.is_file() or not key_path.is_file():
        raise ConfigError(
            "DuMate desktop auth files were not found under %s"
            % auth_path.parent
        )
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise ConfigError(
            "cryptography is required for --from-desktop"
        ) from exc

    try:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("cannot parse DuMate auth.json") from exc
    encrypted = auth.get("cookies")
    if not isinstance(encrypted, str) or not encrypted:
        raise ConfigError("DuMate auth.json does not contain encrypted cookies")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ConfigError("DuMate .cookie-key must be exactly 32 bytes")
    try:
        blob = base64.b64decode(encrypted, validate=True)
    except ValueError as exc:
        raise ConfigError("DuMate auth.json cookie payload is not valid base64") from exc
    if len(blob) < 29:
        raise ConfigError("DuMate encrypted cookie payload is too short")
    iv, tag, ciphertext = blob[:12], blob[12:28], blob[28:]
    try:
        plain = AESGCM(key).decrypt(iv, ciphertext + tag, None)
        raw_cookies = json.loads(plain.decode("utf-8"))
    except Exception as exc:
        raise ConfigError("cannot decrypt DuMate desktop cookies") from exc
    if not isinstance(raw_cookies, list):
        raise ConfigError("DuMate decrypted cookies are not an array")

    cookies = cookies_for_host(raw_cookies)
    if not any(item.name == "bce-sessionid" for item in cookies):
        raise ConfigError(
            "decrypted DuMate cookies do not contain bce-sessionid for %s"
            % TARGET_HOST
        )
    if not csrf_token(cookies):
        raise ConfigError(
            "decrypted DuMate cookies do not contain bce-user-info for %s"
            % TARGET_HOST
        )

    label = ""
    profiles = auth.get("accountProfiles")
    active_id = str(auth.get("activeProfileId", "") or "")
    if isinstance(profiles, list):
        selected = None
        for profile in profiles:
            if not isinstance(profile, Mapping):
                continue
            if active_id and str(profile.get("profileId", "") or "") == active_id:
                selected = profile
                break
        if selected is None and len(profiles) == 1 and isinstance(profiles[0], Mapping):
            selected = profiles[0]
        if selected is not None:
            label = str(
                selected.get("displayName")
                or selected.get("bceAccountId")
                or ""
            )
    return cookies, label


def write_cookie_file(
    path: Path,
    label: str,
    cookies: Sequence[CookieValue],
    *,
    force: bool,
) -> None:
    if path.exists() and not force:
        raise ConfigError("%s already exists; use --force to replace it" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_label = (
        label.replace("|", " ").replace("\r", " ").replace("\n", " ").strip()
        or "desktop"
    )
    content = safe_label + "|" + cookie_header(cookies) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(str(path), flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
    finally:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an ignored DuMate cookie file from the desktop login."
    )
    parser.add_argument(
        "--from-desktop",
        action="store_true",
        help="read auth.json and .cookie-key from the installed DuMate app",
    )
    parser.add_argument(
        "--user-data-dir",
        default="",
        help="override the DuMate desktop user-data directory",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="cookie file path (default: ~/.dumate-cookies)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output file",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="query the account after writing; never claims",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.from_desktop:
        print("use --from-desktop", file=sys.stderr)
        return 2
    env = dict(os.environ)
    if args.user_data_dir:
        env["DUMATE_USER_DATA_DIR"] = args.user_data_dir
    try:
        directory = desktop_user_data_dir(env)
        cookies, label = decrypt_auth_file(
            directory / "auth.json",
            directory / ".cookie-key",
        )
        output = Path(args.output).expanduser()
        write_cookie_file(
            output,
            label,
            cookies,
            force=bool(args.force),
        )
    except ConfigError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "label": label or "desktop",
                "cookie_count": len(cookies),
                "output": str(output),
                "contains_secrets": True,
            },
            ensure_ascii=False,
        )
    )
    if args.verify:
        account = {
            "note": label or "desktop",
            "cookies": cookies,
            "cookie_header": cookie_header(cookies),
            "csrf": csrf_token(cookies),
        }
        result = check_account(account, mode="query")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result.get("ok"):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
