import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dumate_login


class DuMateLoginTests(unittest.TestCase):
    def test_cookie_domain_filter_and_target_order(self):
        cookies = dumate_login.cookies_for_host(
            [
                {
                    "name": "bce-sessionid",
                    "value": "session",
                    "domain": ".baidu.com",
                },
                {
                    "name": "bce-user-info",
                    "value": "csrf",
                    "domain": ".bce.baidu.com",
                },
                {
                    "name": "unrelated",
                    "value": "drop",
                    "domain": ".example.com",
                },
                {"name": "host-only", "value": "keep"},
            ]
        )
        names = [item.name for item in cookies]
        self.assertEqual(
            ["bce-sessionid", "bce-user-info", "host-only"],
            names,
        )

    def test_write_cookie_file_contains_no_plaintext_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.txt"
            cookies = [
                dumate_login.CookieValue("bce-sessionid", "secret-session"),
                dumate_login.CookieValue("bce-user-info", "secret-csrf"),
            ]
            dumate_login.write_cookie_file(
                path,
                "desktop",
                cookies,
                force=False,
            )
            text = path.read_text(encoding="utf-8")
            self.assertEqual(
                "desktop|bce-sessionid=secret-session; "
                "bce-user-info=secret-csrf\n",
                text,
            )
            with self.assertRaises(dumate_login.ConfigError):
                dumate_login.write_cookie_file(
                    path,
                    "desktop",
                    cookies,
                    force=False,
                )

    def test_decrypt_auth_file_round_trip(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            self.skipTest("cryptography is not installed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = bytes(range(32))
            iv = bytes(range(12))
            raw = [
                {
                    "name": "bce-sessionid",
                    "value": "session-value",
                    "domain": ".baidu.com",
                },
                {
                    "name": "bce-user-info",
                    "value": "csrf-value",
                    "domain": ".bce.baidu.com",
                },
            ]
            ciphertext_and_tag = AESGCM(key).encrypt(
                iv,
                json.dumps(raw).encode("utf-8"),
                None,
            )
            ciphertext, tag = (
                ciphertext_and_tag[:-16],
                ciphertext_and_tag[-16:],
            )
            encrypted = base64.b64encode(iv + tag + ciphertext).decode("ascii")
            (root / ".cookie-key").write_bytes(key)
            (root / "auth.json").write_text(
                json.dumps(
                    {
                        "cookies": encrypted,
                        "activeProfileId": "p1",
                        "accountProfiles": [
                            {
                                "profileId": "p1",
                                "displayName": "DuMate Test",
                                "bceAccountId": "account-id",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cookies, label = dumate_login.decrypt_auth_file(
                root / "auth.json",
                root / ".cookie-key",
            )
        self.assertEqual("DuMate Test", label)
        self.assertEqual(
            ["bce-sessionid", "bce-user-info"],
            [item.name for item in cookies],
        )

    def test_desktop_user_data_dir_override(self):
        path = dumate_login.desktop_user_data_dir(
            {"DUMATE_USER_DATA_DIR": "C:/custom/dumate"}
        )
        self.assertEqual(Path("C:/custom/dumate"), path)

    def test_desktop_user_data_dir_windows_default(self):
        path = dumate_login.desktop_user_data_dir(
            {"APPDATA": "C:/Users/test/AppData/Roaming"}
        )
        if sys.platform == "win32":
            self.assertEqual(
                Path("C:/Users/test/AppData/Roaming") / "qianfan-desktop-app",
                path,
            )


if __name__ == "__main__":
    unittest.main()
