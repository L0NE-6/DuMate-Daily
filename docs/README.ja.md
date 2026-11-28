<div align="center">

# 🧭 DuMate Daily

**Baidu DuMate 毎日ログインボーナス · ブーストプラン · 複数アカウント · status → claim → status / points 再確認**

[简体中文](../README.md) · [English](README.en.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Português (BR)](README.pt-BR.md)

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-F472B6?style=for-the-badge" />

</div>

> [!IMPORTANT]
> 本プロジェクトは無料です。転売、有料パッケージ化、有料代行、集客目的の転載、作者の偽装、著作権表示の削除を禁止します。詳細は [NOTICE.md](../NOTICE.md) を参照してください。

## 機能

DuMate Daily は L0NE-6 がオリジナルで保守する独立した単一ファイルスクリプトです。毎日ログインボーナスを確認し、受取可能な場合だけ claim を送信し、状態と累計ポイントを再取得します。

| 項目 | 内容 |
| :--- | :--- |
| 入力 | `DUMATE_COOKIES`、`DUMATE_COOKIE`、または `DUMATE_COOKIE_FILE` |
| 出力 | アカウント別 JSON と最後の集計 JSON |
| 実行環境 | Python 3.9+、`requests`、デスクトップ取込には `cryptography` |
| 配備 | Windows、Linux、Qinglong、GitHub Actions |
| 成功 | `hasIssued=true` かつ `totalPoints` の正の差分 |

## 再確認フロー

```text
GET loginBonusInfo
  ├─ hasIssued=true  -> ALREADY_CLAIMED
  └─ hasIssued=false -> POST loginBonus {}
                         -> GET loginBonusInfo
                         -> hasIssued=true が必要
                         -> totalPoints の増加が必要
                         -> GET quota_overview
```

HTTP 200 や POST 成功だけでは完了ではありません。

## ブーストプラン（同一スクリプト）

ログインボーナスとブーストプランは**同じスクリプト・同じ実行・同じ結果**で処理されます
（別エントリポイントはありません）。サインイン後に成長プラン状態を読み、未完了タスクを
`task_id` だけで順に送信し、サーバーが返す残り回数で抽選します。実物賞は `--contact` で
受け取ります。

```text
GET  growth-plan/page/status
POST growth-plan/tasks                   -> 未完了タスク
POST growth-plan/task/complete {task_id} -> reward_count -> 抽選回数
GET  growth-plan/draw/status
POST growth-plan/draw (X-Bce-Request-Id)
POST growth-plan/prize/claim {draw_record_id, contact}
```

すべてのタスクが自動で完了できるわけではありません。`query` や `suiteName` を持つ
タスクは実行動の証拠が必要で、購読系タスクは実際の購読状態が必要です（`needs_evidence`
で表示）。最終判定はサーバー側で、スクリプトは `task_id` を送るだけで行動を偽装しません。
抽選・交換は Baidu acs+banti 署名を通るため、リスク判定は `RISK_BLOCKED` として報告し、
成功として扱いません。

`--no-booster` · `--booster-only` · `--booster-dry-run` · `--no-draw` ·
`--max-draw N` · `--contact CONTACT` · `--task ID|NAME`

## 認証情報

Cookie は `console.bce.baidu.com` のリクエストから取得し、次を含める必要があります。

- `bce-sessionid`: 状態確認と受取に必要。
- `bce-user-info`: `csrftoken` として送信し、受取に必要。

`DUMATE_COOKIES` は 1 行 1 アカウントです。

```text
account-1|bce-sessionid=<value>; bce-user-info=<value>
account-2|bce-sessionid=<value>; bce-user-info=<value>
```

電話番号形式のラベルは自動的にマスクされます。Cookie と CSRF は JSON やレポートへ出力しません。

## ローカル実行

```bash
python -m pip install -r requirements.txt
export DUMATE_COOKIE='bce-sessionid=<value>; bce-user-info=<value>'
python dumate_daily.py
```

状態確認のみ：

```bash
python dumate_daily.py --query
```

2 番目のアカウントのみ：

```bash
python dumate_daily.py --only 2
```

## デスクトップログイン取込

```bash
python dumate_login.py --from-desktop --verify
```

`auth.json` と `.cookie-key` を読み取り、AES-256-GCM を復号し、対象ホスト用 Cookie を `~/.dumate-cookies` に保存します。DuMate のデータディレクトリには書き込みません。

```bash
python dumate_login.py --from-desktop --output /private/dumate-cookies --verify
export DUMATE_COOKIE_FILE=/private/dumate-cookies
python dumate_daily.py
```

## Qinglong

1. `requests` と `cryptography` をインストールします。
2. `dumate_daily.py` をアップロードします。
3. `DUMATE_COOKIES` または `DUMATE_COOKIE` を設定します。
4. `task dumate_daily.py` をスケジュールします。
5. 北京時間 `00:13` に 1 日 1 回実行します。

## GitHub Actions

`main` への push ではテストを実行します。毎日のスケジュールでは受取と JSON レポート artifact のアップロードを行います。Secret がない場合、定時受取は SKIPPED notice を出して正常終了します。

| Secret | 必須 | 値 |
| :--- | :---: | :--- |
| `DUMATE_COOKIES` | どちらか | 複数アカウント Cookie |
| `DUMATE_COOKIE` | どちらか | 単一アカウント Cookie |

スケジュールは UTC `13 16 * * *`、北京時間 `00:13` です。

## 成功条件

- `ALREADY_CLAIMED`: 事前 `hasIssued=true`。
- `CLAIMED`: POST 後 `hasIssued=true` かつ `totalPoints` 増加。
- `CLAIM_NOT_APPLIED`: POST 後も未発行。
- `CREDIT_UNCONFIRMED`: 発行済みだがポイント未増加。
- `AUTH_EXPIRED`: ログインページ、ログインリダイレクト、HTTP 401/403。

## テスト

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
python -m ruff check dumate_daily.py dumate_login.py tests
```

テストは fake session を使用し、実際のサービスへ接続しません。

## プライバシー

本リポジトリは認証情報や個人情報を保存しません。Cookie ファイル、デスクトップ認証ファイル、レポート、ログは Git の対象外です。

## 免責事項

合法的な個人自動化のために使用してください。特典ルール、インターフェース、資格、残高はサービス提供者が管理します。利用は自己責任です。

---

[中国語 README に戻る](../README.md) · [利用規則](../NOTICE.md) · [投げ銭と Star History](../README.md#star-trail)
