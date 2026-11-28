import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dumate_daily


COOKIE = (
    "bce-sessionid=session-secret; "
    "bce-user-info=csrf-secret; "
    "theme=dark"
)


def _signin_check_account(account, **kwargs):
    """Sign-in tests only: booster has its own test module."""
    kwargs.setdefault("booster", False)
    return dumate_daily.check_account(account, **kwargs)


def _signin_run_accounts(accounts, **kwargs):
    kwargs.setdefault("booster", False)
    return dumate_daily.run_accounts(accounts, **kwargs)


class FakeResponse:
    def __init__(
        self,
        payload=None,
        *,
        status_code=200,
        text=None,
        headers=None,
        json_error=None,
    ):
        self.status_code = status_code
        self.payload = payload
        self.text = (
            text
            if text is not None
            else json.dumps(payload, ensure_ascii=False) if payload is not None else ""
        )
        self.headers = headers or {"Content-Type": "application/json"}
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected GET")
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected POST")
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class SessionFactory:
    def __init__(self, responses):
        self.responses = [list(group) for group in responses]
        self.sessions = []

    def __call__(self):
        session = FakeSession(self.responses.pop(0))
        self.sessions.append(session)
        return session


def api(payload):
    return FakeResponse(
        {
            "code": 0,
            "success": True,
            "result": payload,
        }
    )


def bonus(issued, points, times=1):
    return api(
        {
            "hasIssued": issued,
            "totalPoints": str(points),
            "totalTimes": times,
        }
    )


def quota(total, used):
    return api({"totalPoints": str(total), "usedPoints": str(used)})


def account():
    return dumate_daily.load_accounts(
        {"DUMATE_COOKIE": "账号1|" + COOKIE}
    )[0]


class DuMateDailyTests(unittest.TestCase):
    def test_parse_cookie_and_csrf(self):
        cookies = dumate_daily.parse_cookie(COOKIE)
        names = {item.name: item.value for item in cookies}
        self.assertEqual("session-secret", names["bce-sessionid"])
        self.assertEqual("csrf-secret", names["bce-user-info"])
        self.assertEqual("csrf-secret", dumate_daily.csrf_token(cookies))
        self.assertIn(
            "bce-sessionid=session-secret",
            dumate_daily.cookie_header(cookies),
        )

    def test_cookie_parser_respects_quoted_semicolon(self):
        cookies = dumate_daily.parse_cookie(
            'bce-sessionid="session;secret"; bce-user-info=csrf'
        )
        rendered = dumate_daily.cookie_header(cookies)
        self.assertIn('bce-sessionid="session;secret"', rendered)
        self.assertIn("bce-user-info=csrf", rendered)

    def test_load_multiple_accounts_and_mask_phone_label(self):
        accounts = dumate_daily.load_accounts(
            {
                "DUMATE_COOKIES": (
                    "13800138000|bce-sessionid=a; bce-user-info=x\n"
                    "second|bce-sessionid=b; bce-user-info=y"
                )
            }
        )
        self.assertEqual(2, len(accounts))
        self.assertEqual("138****8000", accounts[0]["note"])
        self.assertEqual("second", accounts[1]["note"])

    def test_cookie_file_is_supported_without_printing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.txt"
            path.write_text(
                "DUMATE_COOKIES=file-account|" + COOKIE + "\n",
                encoding="utf-8",
            )
            accounts = dumate_daily.load_accounts(
                {"DUMATE_COOKIE_FILE": str(path)}
            )
        self.assertEqual(1, len(accounts))
        self.assertEqual("file-account", accounts[0]["note"])
        self.assertIn("bce-sessionid=session-secret", accounts[0]["cookie_header"])

    def test_claim_requires_positive_points_delta(self):
        factory = SessionFactory(
            [
                [
                    bonus(False, 100, 5),
                    quota(1000, 200),
                    api(True),
                    bonus(True, 150, 6),
                    quota(1050, 200),
                ]
            ]
        )
        result = _signin_check_account(
            account(),
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("CLAIMED", result["result"])
        self.assertTrue(result["ok"])
        self.assertEqual(50, result["credit"])
        self.assertEqual(850, result["quota_remaining"])
        self.assertEqual(
            ["GET", "GET", "POST", "GET", "GET"],
            [call[0] for call in factory.sessions[0].calls],
        )
        post_headers = factory.sessions[0].calls[2][2]["headers"]
        self.assertEqual("csrf-secret", post_headers["csrftoken"])
        self.assertEqual(
            "XMLHttpRequest",
            post_headers["X-Requested-With"],
        )
        self.assertEqual("https://example.test", post_headers["Origin"])

    def test_already_claimed_skips_post(self):
        factory = SessionFactory(
            [[bonus(True, 900, 30), quota(2000, 500)]]
        )
        result = _signin_check_account(
            account(),
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("ALREADY_CLAIMED", result["result"])
        self.assertTrue(result["ok"])
        self.assertEqual(
            ["GET", "GET"],
            [call[0] for call in factory.sessions[0].calls],
        )

    def test_query_mode_does_not_claim(self):
        factory = SessionFactory(
            [[bonus(False, 100, 2), quota(500, 100)]]
        )
        result = _signin_check_account(
            account(),
            mode="query",
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("AVAILABLE", result["result"])
        self.assertFalse(result["claimed"])
        self.assertEqual(
            ["GET", "GET"],
            [call[0] for call in factory.sessions[0].calls],
        )

    def test_post_success_without_points_delta_is_not_success(self):
        factory = SessionFactory(
            [
                [
                    bonus(False, 100, 2),
                    quota(500, 100),
                    api(True),
                    bonus(True, 100, 3),
                    quota(500, 100),
                ]
            ]
        )
        result = _signin_check_account(
            account(),
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("CREDIT_UNCONFIRMED", result["result"])
        self.assertFalse(result["ok"])
        self.assertIsNone(result["credit"])

    def test_post_success_but_still_unissued_is_failure(self):
        factory = SessionFactory(
            [
                [
                    bonus(False, 100, 2),
                    quota(500, 100),
                    api(True),
                    bonus(False, 100, 2),
                    quota(500, 100),
                ]
            ]
        )
        result = _signin_check_account(
            account(),
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("CLAIM_NOT_APPLIED", result["result"])
        self.assertFalse(result["ok"])

    def test_html_login_page_is_auth_expired(self):
        factory = SessionFactory(
            [
                [
                    FakeResponse(
                        status_code=200,
                        text="<!DOCTYPE html><html>请登录</html>",
                        headers={"Content-Type": "text/html"},
                    )
                ]
            ]
        )
        result = _signin_check_account(
            account(),
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("AUTH_EXPIRED", result["result"])
        self.assertFalse(result["ok"])

    def test_redirect_to_login_is_auth_expired(self):
        factory = SessionFactory(
            [
                [
                    FakeResponse(
                        status_code=302,
                        text="",
                        headers={"Location": "https://login.bce.baidu.com/"},
                    )
                ]
            ]
        )
        result = _signin_check_account(
            account(),
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("AUTH_EXPIRED", result["result"])

    def test_missing_csrf_blocks_claim(self):
        missing = dumate_daily.load_accounts(
            {"DUMATE_COOKIE": "bce-sessionid=session-only"}
        )[0]
        factory = SessionFactory([])
        result = _signin_check_account(
            missing,
            base_url="https://example.test",
            session_factory=factory,
        )
        self.assertEqual("CREDENTIAL_INCOMPLETE", result["result"])
        self.assertEqual([], factory.sessions)

    def test_api_error_redacts_cookie_values(self):
        factory = SessionFactory(
            [
                [
                    FakeResponse(
                        {
                            "code": 500,
                            "success": False,
                            "message": "rejected session-secret and csrf-secret",
                        }
                    )
                ]
            ]
        )
        result = _signin_check_account(
            account(),
            base_url="https://example.test",
            session_factory=factory,
        )
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertEqual("BUSINESS_ERROR", result["result"])
        self.assertNotIn("session-secret", rendered)
        self.assertNotIn("csrf-secret", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_multi_account_isolation_and_summary(self):
        accounts = dumate_daily.load_accounts(
            {
                "DUMATE_COOKIES": (
                    "first|bce-sessionid=a; bce-user-info=x\n"
                    "second|bce-sessionid=b; bce-user-info=y"
                )
            }
        )
        factory = SessionFactory(
            [
                [bonus(True, 10, 1), quota(100, 20)],
                [
                    FakeResponse(
                        status_code=401,
                        payload={"message": "expired"},
                    )
                ],
            ]
        )
        output = []
        results = _signin_run_accounts(
            accounts,
            base_url="https://example.test",
            session_factory=factory,
            output=output.append,
        )
        self.assertEqual("ALREADY_CLAIMED", results[0]["result"])
        self.assertEqual("AUTH_EXPIRED", results[1]["result"])
        self.assertIsNot(factory.sessions[0], factory.sessions[1])
        self.assertTrue(all(session.closed for session in factory.sessions))
        summary = dumate_daily.build_summary(results)
        self.assertEqual(1, summary["success"])
        self.assertEqual(1, summary["failed"])
        self.assertEqual(1, summary["already_claimed"])
        self.assertNotIn("session-secret", json.dumps(output))

    def test_main_summary_is_last_and_config_error_returns_two(self):
        factory = SessionFactory(
            [[bonus(True, 10, 1), quota(100, 20)]]
        )
        output = []
        code = dumate_daily.main(
            ["--no-booster", "--no-notify"],
            env={"DUMATE_COOKIE": COOKIE},
            session_factory=factory,
            output=output.append,
        )
        self.assertEqual(0, code)
        self.assertEqual("dumate", output[-1]["provider"])
        self.assertEqual(1, output[-1]["success"])

        config_output = []
        code = dumate_daily.main(
            ["--no-booster"],
            env={},
            session_factory=SessionFactory([]),
            output=config_output.append,
        )
        self.assertEqual(2, code)
        self.assertEqual("CONFIG_ERROR", config_output[0]["result"])
        self.assertEqual("dumate", config_output[-1]["provider"])

    def test_main_only_filters_one_account(self):
        accounts_env = {
            "DUMATE_COOKIES": (
                "first|bce-sessionid=a; bce-user-info=x\n"
                "second|bce-sessionid=b; bce-user-info=y"
            )
        }
        factory = SessionFactory(
            [[bonus(True, 10, 1), quota(100, 20)]]
        )
        output = []
        with contextlib.redirect_stdout(io.StringIO()):
            code = dumate_daily.main(
                ["--no-booster", "--only", "2", "--no-notify"],
                env=accounts_env,
                session_factory=factory,
                output=output.append,
            )
        self.assertEqual(0, code)
        self.assertEqual(1, output[-1]["accounts"])
        self.assertEqual("second", output[0]["account"])


if __name__ == "__main__":
    unittest.main()
