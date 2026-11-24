<div align="center">

# 🧭 DuMate Daily

**百度搭子每日登入積分 · 多帳號隔離 · status → claim → status / points 嚴格回讀**

[简体中文](../README.md) · [English](README.en.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Português (BR)](README.pt-BR.md)

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-F472B6?style=for-the-badge" />

</div>

> [!IMPORTANT]
> 本專案永久免費。禁止倒賣、付費包裝、代部署收費、搬運引流、冒充作者或刪除版權資訊。完整規則見 [NOTICE.md](../NOTICE.md)。

## 功能

DuMate Daily 是 L0NE-6 原創維護的獨立單檔腳本。它會檢查百度搭子每日登入積分，可領取時提交一次領取，並再次讀取狀態與累計簽到積分。

| 項目 | 說明 |
| :--- | :--- |
| 輸入 | `DUMATE_COOKIES`、`DUMATE_COOKIE` 或 `DUMATE_COOKIE_FILE` |
| 輸出 | 每帳號 JSON 與最後一筆彙總 JSON |
| 執行環境 | Python 3.9+、`requests`；桌面登入匯入需要 `cryptography` |
| 部署 | Windows、Linux、青龍、GitHub Actions |
| 成功 | `hasIssued=true` 且 `totalPoints` 正差額大於 0 |

## 回讀流程

```text
GET loginBonusInfo
  ├─ hasIssued=true  -> ALREADY_CLAIMED
  └─ hasIssued=false -> POST loginBonus {}
                         -> GET loginBonusInfo
                         -> hasIssued 必須為 true
                         -> totalPoints 必須增加
                         -> GET quota_overview
```

只有 HTTP 200 或 POST 成功回執，不算完成。

## 憑據

Cookie 必須來自 `console.bce.baidu.com` 請求，且包含：

- `bce-sessionid`：查詢與領取都需要；
- `bce-user-info`：作為 `csrftoken` 請求頭，領取需要。

`DUMATE_COOKIES` 每行一個帳號：

```text
帳號一|bce-sessionid=<value>; bce-user-info=<value>
帳號二|bce-sessionid=<value>; bce-user-info=<value>
```

手機號標籤會自動遮罩；Cookie 與 CSRF 不會寫入 JSON 或報告。

## 本機執行

```bash
python -m pip install -r requirements.txt
export DUMATE_COOKIE='bce-sessionid=<value>; bce-user-info=<value>'
python dumate_daily.py
```

只查狀態：

```bash
python dumate_daily.py --query
```

只跑第二個帳號：

```bash
python dumate_daily.py --only 2
```

## 桌面登入匯入

```bash
python dumate_login.py --from-desktop --verify
```

工具只讀 `auth.json` 與 `.cookie-key`，解密 AES-256-GCM 資料，按主機域名過濾 Cookie，並寫入 `~/.dumate-cookies`。不會寫回百度搭子資料目錄。

```bash
python dumate_login.py --from-desktop --output /private/dumate-cookies --verify
export DUMATE_COOKIE_FILE=/private/dumate-cookies
python dumate_daily.py
```

## 青龍

1. 安裝 `requests` 與 `cryptography`。
2. 上傳 `dumate_daily.py`，需要本機登入匯入時再上傳 `dumate_login.py`。
3. 設定 `DUMATE_COOKIES` 或 `DUMATE_COOKIE`。
4. 建立排程，命令填 `task dumate_daily.py`。
5. 建議北京時間每天 `00:13` 執行一次。

## GitHub Actions

工作流在 `main` push 時執行測試；每日排程會領取並上傳 JSON 報告 artifact。未設定憑據 Secret 時，定時任務會輸出 SKIPPED notice 並正常結束。

| Secret | 必填 | 值 |
| :--- | :---: | :--- |
| `DUMATE_COOKIES` | 二選一 | 多帳號 Cookie |
| `DUMATE_COOKIE` | 二選一 | 單帳號 Cookie |

排程為 UTC `13 16 * * *`，即北京時間 `00:13`。

## 成功判據

- `ALREADY_CLAIMED`：領取前 `hasIssued=true`。
- `CLAIMED`：POST 後 `hasIssued=true`，且 `totalPoints` 增加。
- `CLAIM_NOT_APPLIED`：POST 後仍未發放。
- `CREDIT_UNCONFIRMED`：已發放但積分未增加。
- `AUTH_EXPIRED`：登入頁、登入跳轉、HTTP 401 或 403。

## 測試

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
python -m ruff check dumate_daily.py dumate_login.py tests
```

測試使用 fake session，不連線真實服務。

## 隱私

本倉庫不保存憑據或個人資料。Cookie 檔案、桌面認證檔案、報告與日誌均由 Git 忽略。

## 免責聲明

本專案供合法的個人自動化使用。活動規則、介面、資格與積分由服務方決定，使用風險自負。

---

[返回簡體中文 README](../README.md) · [使用規則](../NOTICE.md) · [投喂與星軌](../README.md#star-trail)
