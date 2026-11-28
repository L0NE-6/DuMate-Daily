# Changelog

All notable changes to DuMate Daily are documented in this file.

## [1.1.0] - 2026-11-28

### Added

- `dumate_booster.py`: 充能计划（growth plan）自动化 —— 查任务、逐个完成未完成任务、
  抽奖、实物奖领奖。账号与签到共用同一套 Cookie / csrftoken。
- 充能计划接口来自官网前端 bundle：`activity/growth-plan/{page/status,tasks,task/complete,
  draw,draw/status,prize/claim}`，任务类型覆盖前端 `taskType` 全枚举。
- 写操作安全开关：`--dry-run` 零写操作、`--no-draw` 只做任务、`--max-draw` 限制抽奖次数、
  `--contact` 用于实物奖领奖。
- 风控显式失败：服务端返回风控提示时报 `RISK_BLOCKED`，不把拦截当成功。
- 新增 `tests/test_dumate_booster.py`（15 个用例），全量 36 个单测通过。

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
