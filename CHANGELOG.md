# Changelog

All notable changes to DuMate Daily are documented in this file.

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
