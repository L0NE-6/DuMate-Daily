# Changelog

All notable changes to DuMate Daily are documented in this file.

## [1.1.0] - 2026-11-28

### Added

- 充能计划（growth plan）**并入 `dumate_daily.py`**，不新增独立脚本、不新增凭据：
  签到之后接着读活动状态、完成未完成任务、抽奖、领实物奖，全部写在同一条账号结果里。
- 接口取自官网前端 bundle：`activity/growth-plan/{page/status,tasks,task/complete,
  draw,draw/status,prize/claim}`，覆盖前端 `taskType` 全枚举。
- 任务分型：`query` / `suiteName` 与行为型、订阅型任务标记 `needs_evidence`，报告里
  明确「可能不通过」——服务端才是最终判定，脚本只提交 `task_id`。
- 写操作开关：`--no-booster`、`--booster-only`、`--booster-dry-run`、`--no-draw`、
  `--max-draw N`、`--contact`、`--task ID|NAME`。
- 风控显式失败：写操作走百度 acs+banti 签名，风控响应报 `RISK_BLOCKED`，不静默成功。
- 汇总新增 `booster` 段（完成任务数 / 失败任务数 / 抽奖次数）。

### Changed

- README（中文）与 5 份翻译（en / zh-Hant / ja / ko / pt-BR）同步补充充能计划章节、
  参数表与「能自动完成哪些任务」的判定口径。
- `pyproject.toml` 描述改为「daily login bonus + booster plan」。

### Tests

- 新增 `tests/test_dumate_booster.py`（任务解析、dry-run 零写入、风控、`--task` 过滤、
  签到与充能合并执行）；全量 41 个单测通过。

## [1.0.0] - 2026-11-24

### Added

- Standalone Baidu DuMate daily login-bonus runner.
- Multi-account Cookie parsing with isolated requests sessions.
- Strict `loginBonusInfo -> loginBonus -> loginBonusInfo` readback.
- Positive `totalPoints` delta requirement before reporting a new claim.
- Distinction between already claimed, newly claimed, not applied, and credit
  not confirmed.
- Desktop `auth.json` reader with AES-256-GCM decryption and domain filtering.
- Ignored local cookie-file workflow via `DUMATE_COOKIE_FILE`.
- Query mode, single-account selection, JSON Lines output, and aggregate report.
- PushPlus, Bark, WxPusher, ServerChan, WeCom, DingTalk, and generic webhook
  notifications.
- Windows, Linux, Qinglong, and GitHub Actions documentation.
- Chinese README, five translated guides, donation QR assets, and tests.
