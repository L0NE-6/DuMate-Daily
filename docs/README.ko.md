<div align="center">

# 🧭 DuMate Daily

**Baidu DuMate 일일 로그인 보너스 · 다중 계정 · status → claim → status / points 재확인**

[简体中文](../README.md) · [English](README.en.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Português (BR)](README.pt-BR.md)

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-F472B6?style=for-the-badge" />

</div>

> [!IMPORTANT]
> 이 프로젝트는 무료입니다. 재판매, 유료 패키징, 유료 대행 배포, 유입용 재배포, 작성자 사칭, 저작권 표시 제거를 금지합니다. 자세한 내용은 [NOTICE.md](../NOTICE.md)를 확인하세요.

## 기능

DuMate Daily는 L0NE-6이 독자적으로 유지보수하는 단일 파일 스크립트입니다. 일일 로그인 보너스를 확인하고, 받을 수 있을 때만 claim을 보낸 뒤 상태와 누적 포인트를 다시 읽습니다.

| 항목 | 설명 |
| :--- | :--- |
| 입력 | `DUMATE_COOKIES`, `DUMATE_COOKIE`, `DUMATE_COOKIE_FILE` |
| 출력 | 계정별 JSON과 마지막 집계 JSON |
| 실행 환경 | Python 3.9+, `requests`; 데스크톱 가져오기는 `cryptography` |
| 배포 | Windows, Linux, Qinglong, GitHub Actions |
| 성공 | `hasIssued=true`와 양수 `totalPoints` 차이 |

## 재확인 흐름

```text
GET loginBonusInfo
  ├─ hasIssued=true  -> ALREADY_CLAIMED
  └─ hasIssued=false -> POST loginBonus {}
                         -> GET loginBonusInfo
                         -> hasIssued=true 필요
                         -> totalPoints 증가 필요
                         -> GET quota_overview
```

HTTP 200 또는 POST 성공만으로는 완료가 아닙니다.

## 자격 증명

Cookie는 `console.bce.baidu.com` 요청에서 가져와야 하며 다음이 필요합니다.

- `bce-sessionid`: 상태 조회와 수령에 필요.
- `bce-user-info`: `csrftoken` 헤더로 전송하며 수령에 필요.

`DUMATE_COOKIES`는 한 줄에 계정 하나입니다.

```text
account-1|bce-sessionid=<value>; bce-user-info=<value>
account-2|bce-sessionid=<value>; bce-user-info=<value>
```

전화번호 형식 라벨은 자동 마스킹됩니다. Cookie와 CSRF는 JSON 또는 보고서에 기록하지 않습니다.

## 로컬 실행

```bash
python -m pip install -r requirements.txt
export DUMATE_COOKIE='bce-sessionid=<value>; bce-user-info=<value>'
python dumate_daily.py
```

상태만 확인:

```bash
python dumate_daily.py --query
```

두 번째 계정만 실행:

```bash
python dumate_daily.py --only 2
```

## 데스크톱 로그인 가져오기

```bash
python dumate_login.py --from-desktop --verify
```

`auth.json`과 `.cookie-key`를 읽어 AES-256-GCM을 복호화하고, 콘솔 호스트용 Cookie를 `~/.dumate-cookies`에 저장합니다. DuMate 데이터 디렉터리에는 쓰지 않습니다.

```bash
python dumate_login.py --from-desktop --output /private/dumate-cookies --verify
export DUMATE_COOKIE_FILE=/private/dumate-cookies
python dumate_daily.py
```

## Qinglong

1. `requests`와 `cryptography`를 설치합니다.
2. `dumate_daily.py`를 업로드합니다.
3. `DUMATE_COOKIES` 또는 `DUMATE_COOKIE`를 설정합니다.
4. `task dumate_daily.py` 예약 작업을 만듭니다.
5. 베이징 시간 `00:13`에 하루 한 번 실행합니다.

## GitHub Actions

`main` push에서는 테스트를 실행합니다. 일일 예약 실행은 수령 후 JSON 보고서 artifact를 업로드합니다. Secret이 없으면 예약 수령은 SKIPPED notice를 남기고 정상 종료합니다.

| Secret | 필수 | 값 |
| :--- | :---: | :--- |
| `DUMATE_COOKIES` | 둘 중 하나 | 다중 계정 Cookie |
| `DUMATE_COOKIE` | 둘 중 하나 | 단일 계정 Cookie |

예약은 UTC `13 16 * * *`, 베이징 시간 `00:13`입니다.

## 성공 기준

- `ALREADY_CLAIMED`: 사전 `hasIssued=true`.
- `CLAIMED`: POST 후 `hasIssued=true`이고 `totalPoints` 증가.
- `CLAIM_NOT_APPLIED`: POST 후에도 미발급.
- `CREDIT_UNCONFIRMED`: 발급됐지만 포인트 미증가.
- `AUTH_EXPIRED`: 로그인 페이지, 로그인 리다이렉트, HTTP 401/403.

## 테스트

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
python -m ruff check dumate_daily.py dumate_login.py tests
```

테스트는 fake session을 사용하며 실제 서비스에 연결하지 않습니다.

## 개인정보

이 저장소는 자격 증명이나 개인정보를 저장하지 않습니다. Cookie 파일, 데스크톱 인증 파일, 보고서, 로그는 Git에서 제외됩니다.

## 면책

합법적인 개인 자동화에 사용하세요. 혜택 규칙, 인터페이스, 자격, 잔액은 서비스 제공자가 관리합니다. 사용 책임은 사용자에게 있습니다.

---

[중국어 README로 돌아가기](../README.md) · [사용 규칙](../NOTICE.md) · [후원 및 Star History](../README.md#star-trail)
