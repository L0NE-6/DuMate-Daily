<div align="center">

# 🧭 DuMate Daily

**Baidu DuMate daily login bonus · booster plan · multi-account isolation · status → claim → status / points**

[简体中文](../README.md) · [English](README.en.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Português (BR)](README.pt-BR.md)

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-F472B6?style=for-the-badge" />

</div>

> [!IMPORTANT]
> This project is free. Resale, paywalling, paid redeployment, traffic-baiting
> redistribution, author impersonation, and removal of copyright notices are
> prohibited. See [NOTICE.md](../NOTICE.md).

## What It Does

DuMate Daily is an original L0NE-6 maintenance project. It checks the daily
login bonus, claims it when available, and verifies the result through a second
`loginBonusInfo` read.

| Item | Description |
| :--- | :--- |
| Input | `DUMATE_COOKIES`, `DUMATE_COOKIE`, or `DUMATE_COOKIE_FILE` |
| Output | Per-account JSON and a final aggregate JSON |
| Runtime | Python 3.9+, `requests`; `cryptography` for desktop import |
| Deploy | Windows, Linux, Qinglong, GitHub Actions |
| Success | `hasIssued=true` plus a positive `totalPoints` delta |

## Readback Flow

```text
GET loginBonusInfo
  ├─ hasIssued=true  -> ALREADY_CLAIMED
  └─ hasIssued=false -> POST loginBonus {}
                         -> GET loginBonusInfo
                         -> hasIssued must be true
                         -> totalPoints delta must be positive
                         -> GET quota_overview
```

An HTTP 200 or a successful POST response alone is not success.

## Booster Plan (same script)

The login bonus and the booster plan run in **one script, one run, one result** —
there is no second entry point. After sign-in the script reads the growth-plan
status, submits every unfinished task (`task_id` only), then draws with the
remaining draw count. Physical prizes are claimed with `--contact`.

```text
GET  growth-plan/page/status
POST growth-plan/tasks                   -> unfinished tasks
POST growth-plan/task/complete {task_id} -> reward_count -> draw count
GET  growth-plan/draw/status
POST growth-plan/draw (X-Bce-Request-Id)
POST growth-plan/prize/claim {draw_record_id, contact}
```

Not every task can be completed automatically. Tasks carrying `query` or
`suiteName` are gated by the front-end until real evidence exists, and
subscription tasks need a real subscription; those are flagged
`needs_evidence`. The server always has the final say — the script submits a
`task_id` and never fabricates task behaviour. Draw/redeem endpoints go through
Baidu acs+banti signing, so a risk reply is reported as `RISK_BLOCKED`, never as
success.

`--no-booster` · `--booster-only` · `--booster-dry-run` · `--no-draw` ·
`--max-draw N` · `--contact CONTACT` · `--task ID|NAME`

## Credentials

The Cookie must come from a `console.bce.baidu.com` request and include:

- `bce-sessionid`: required for status and claim;
- `bce-user-info`: sent as `csrftoken` and required for claim.

`DUMATE_COOKIES` accepts one account per line:

```text
account-1|bce-sessionid=<value>; bce-user-info=<value>
account-2|bce-sessionid=<value>; bce-user-info=<value>
```

Phone-number labels are masked automatically. Cookie and CSRF values are never
written to JSON output or reports.

## Local Run

```bash
python -m pip install -r requirements.txt
export DUMATE_COOKIE='bce-sessionid=<value>; bce-user-info=<value>'
python dumate_daily.py
```

Status only:

```bash
python dumate_daily.py --query
```

One account only:

```bash
python dumate_daily.py --only 2
```

## Desktop Session Import

```bash
python dumate_login.py --from-desktop --verify
```

The helper reads `auth.json` and `.cookie-key` from the installed DuMate app,
decrypts the AES-256-GCM payload, filters cookies for the console host, and
writes `~/.dumate-cookies`. It never writes into the DuMate data directory.

Use a custom file:

```bash
python dumate_login.py --from-desktop --output /private/dumate-cookies --verify
export DUMATE_COOKIE_FILE=/private/dumate-cookies
python dumate_daily.py
```

## Qinglong

1. Install `requests` and `cryptography`.
2. Upload `dumate_daily.py`; optionally upload `dumate_login.py`.
3. Add `DUMATE_COOKIES` or `DUMATE_COOKIE`.
4. Create a scheduled task with `task dumate_daily.py`.
5. Run once per day at 00:13 Beijing time.

## GitHub Actions

The included workflow runs tests on every push to `main`. The daily schedule
claims the bonus and uploads a JSON report artifact. Without a credential
Secret, the scheduled claim is skipped with an explicit notice.

| Secret | Required | Value |
| :--- | :---: | :--- |
| `DUMATE_COOKIES` | Either one | Multi-account Cookies |
| `DUMATE_COOKIE` | Either one | Single-account Cookie |

The schedule is `13 16 * * *` UTC, 00:13 Beijing time. GitHub schedules are
best-effort and may be delayed.

## Success Criteria

- `ALREADY_CLAIMED`: pre-claim `hasIssued=true`.
- `CLAIMED`: post-claim `hasIssued=true` and `totalPoints` increased.
- `CLAIM_NOT_APPLIED`: post-claim `hasIssued=false`.
- `CREDIT_UNCONFIRMED`: post-claim `hasIssued=true` but points did not increase.
- `AUTH_EXPIRED`: login page, login redirect, HTTP 401, or HTTP 403.

## Test

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
python -m ruff check dumate_daily.py dumate_login.py tests
```

Tests use fake sessions and never contact the live service.

## Privacy

No credentials or personal data are stored in this repository. Cookie files,
desktop authentication files, reports, and logs are ignored by Git.

## Disclaimer

Use this project for lawful personal automation. Activity rules, interfaces,
eligibility, and balances are controlled by the service provider. Use is at
your own risk.

---

[Back to Chinese README](../README.md) · [Usage policy](../NOTICE.md) · [Donation and Star History](../README.md#star-trail)
