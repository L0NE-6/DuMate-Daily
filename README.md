<div align="center">

<sub><strong>L0NE-6 · DUMATE SIGNAL</strong></sub>

# 🧭 DuMate Daily

**百度搭子每日登录积分 · 多账号隔离 · status → claim → status / points 严格回读**

> 当前版本：**v1.0.0**（2026-11-24） · 独立仓库维护版 · 单文件运行 · 不把 HTTP 200 冒充成功

[简体中文](README.md) · [English](docs/README.en.md) · [繁體中文](docs/README.zh-Hant.md) · [日本語](docs/README.ja.md) · [한국어](docs/README.ko.md) · [Português (BR)](docs/README.pt-BR.md)

🔁 多账号隔离 · 🧾 JSON 报告 · ✅ 积分差额回读 · 🛡️ 凭据脱敏 · 🐧 青龙友好 · ☁️ GitHub Actions · 🧪 单元测试

<img src="https://img.shields.io/github/v/release/L0NE-6/DuMate-Daily?style=for-the-badge&label=Release&color=2ea44f&logo=github" />
<img src="https://img.shields.io/github/stars/L0NE-6/DuMate-Daily?style=for-the-badge&label=Stars&color=FFC75F&logo=github" />
<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20%E9%9D%92%E9%BE%99-4EAA25?style=for-the-badge&logo=linux&logoColor=white" />
<img src="https://img.shields.io/badge/Deploy-%E9%9D%92%E9%BE%99%20%7C%20GitHub%20Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-F472B6?style=for-the-badge" />
<a href="https://github.com/L0NE-6/DuMate-Daily/releases"><img src="https://img.shields.io/badge/%E2%AC%87%20Download-Releases-2ea44f?style=for-the-badge&logo=github" /></a>

[✨ 30 秒速览](#quick-overview) · [🔐 凭据格式](#credentials) · [🚀 青龙部署](#qinglong) · [☁️ GitHub Actions](#actions) · [⌨️ 命令行](#cli) · [✅ 成功判据](#success) · [🚫 使用边界](#usage-policy) · [✦ 星轨](#star-trail)

</div>

---

<a id="usage-policy"></a>
## 🚫 使用边界与转载声明

> [!IMPORTANT]
> **官方版本永久免费。禁止倒卖。** 未经作者书面许可，禁止付费包装、搬运引流、冒充作者，或使用作者身份与收款码制造官方授权假象。

本仓库、脚本、部署说明和 Release 下载始终免费公开。禁止把本项目包装为付费资源、内部版、独家版、会员权益、收费课程、代部署服务或包更新服务；禁止搬运到其他账号、群组、频道、网盘、电商和付费平台进行涨粉、截流、倒卖或引流；禁止删除作者与版权信息后冒充原创。

官方仓库和 Release 始终免费。第三方以“下载费、激活费、内部版、代部署、会员门槛”等名义收费，均与作者无关。完整规则见 **[NOTICE.md](NOTICE.md)**。

---

<a id="quick-overview"></a>
## ✨ 30 秒速览

| 维度 | 说明 |
| :--- | :--- |
| **做什么** | 检查百度搭子每日登录积分，未领取时领取，并用服务端状态和积分差额回读。 |
| **输入** | `DUMATE_COOKIES`、`DUMATE_COOKIE`，或本机忽略文件 `DUMATE_COOKIE_FILE`。 |
| **输出** | 每账号一条 JSON、最后一条汇总 JSON、签到前后状态、积分差额、积分余额。 |
| **部署** | Windows、Linux、青龙面板、GitHub Actions。 |
| **依赖** | Python 3.9+；运行依赖 `requests`，桌面登录导入额外使用 `cryptography`。 |
| **成功判据** | 新领取必须同时满足 `hasIssued=true` 和 `totalPoints` 正差额。 |

## ✨ 这是什么

DuMate Daily 是 L0NE-6 原创维护的独立签到脚本。它只处理百度搭子的每日登录积分：

1. 读取领取前状态；
2. 已领取时直接返回 `ALREADY_CLAIMED`；
3. 未领取时提交一次领取；
4. 再次读取 `hasIssued`、累计签到天数和累计签到积分；
5. 只有状态翻转为已领取且积分确实增加，才返回 `CLAIMED`；
6. 最后读取积分总览，记录套餐总积分、已用积分和剩余积分。

脚本不会把“POST 成功”“HTTP 200”或“页面提示成功”单独当成领取完成。

---

## 🔁 协议与回读流程

```text
GET /api/dumate/points/loginBonusInfo
  |
  +-- hasIssued=true  -> ALREADY_CLAIMED
  |
  +-- hasIssued=false -> POST /api/dumate/points/loginBonus {}
                           |
                           +-> GET loginBonusInfo again
                           +-> hasIssued must be true
                           +-> totalPoints delta must be > 0
                           +-> GET quota_overview
                           +-> CLAIMED / CLAIM_NOT_APPLIED / CREDIT_UNCONFIRMED
```

### 关键字段

| 字段 | 用途 |
| :--- | :--- |
| `hasIssued` | 今日登录积分是否已经发放 |
| `totalPoints` | 累计签到积分，用于计算领取前后差额 |
| `totalTimes` | 累计签到天数 |
| `totalPoints` / `usedPoints` | 积分总览中的总额与已用额，二者之差用于展示剩余积分 |

### 结果判定

| 场景 | 结论 |
| :--- | :--- |
| 领取前 `hasIssued=true` | `ALREADY_CLAIMED` |
| POST 后 `hasIssued=true` 且积分增加 | `CLAIMED` |
| POST 后 `hasIssued=true` 但积分未增加 | `CREDIT_UNCONFIRMED`，失败 |
| POST 后 `hasIssued=false` | `CLAIM_NOT_APPLIED`，失败 |
| 登录页、302 登录跳转、401/403 | `AUTH_EXPIRED`，失败 |
| 状态字段缺失或无法解析 | `STATUS_UNRECOGNIZED`，失败 |

---

<a id="credentials"></a>
## 🔐 凭据格式

| 变量 | 必填 | 说明 |
| :--- | :---: | :--- |
| `DUMATE_COOKIES` | 二选一 | 多账号 Cookie，换行分隔；每行可写 `备注\|Cookie`。 |
| `DUMATE_COOKIE` | 二选一 | 单账号 Cookie，仅在 `DUMATE_COOKIES` 为空时使用。 |
| `DUMATE_COOKIE_FILE` | 二选一 | 本地忽略文件路径；未设置时尝试读取 `~/.dumate-cookies`。 |
| `DUMATE_BASE_URL` | ⬜ | 仅用于自建测试或接口迁移，默认官方控制台。 |

### 必须包含的 Cookie

- `bce-sessionid`：登录态，查询和领取都需要；
- `bce-user-info`：作为 `csrftoken` 请求头发送，领取需要。

关键 Cookie 是 httpOnly，浏览器控制台执行 `document.cookie` 拿不到。请从 `console.bce.baidu.com` 的 **DevTools → Network → 请求头 → Cookie** 复制整行值。

### 多账号示例

```text
账号一|bce-sessionid=<value>; bce-user-info=<value>; theme=dark
账号二|bce-sessionid=<value>; bce-user-info=<value>
```

手机号标签会自动掩码；脚本不会把 Cookie 或 CSRF 写入 JSON、日志和报告。

### 凭据从哪来

**方式一：浏览器请求头**

1. 打开 <https://login.bce.baidu.com/?from=oa_dumate&redirect=https%3A%2F%2Fconsole.bce.baidu.com%2F>；
2. 登录后进入 `console.bce.baidu.com`；
3. 按 F12 打开 DevTools，切换到 Network；
4. 刷新页面，点任意控制台 API 请求；
5. 在 Request Headers 中复制完整 `Cookie` 值。

**方式二：桌面端登录态**

已安装百度搭子并完成登录时，可只读导入本机桌面会话：

```powershell
python -m pip install -r requirements.txt
python dumate_login.py --from-desktop --verify
```

默认写入 `~/.dumate-cookies`，文件权限尽量设为仅当前用户可读写。脚本只读取桌面端的 `auth.json` 和 `.cookie-key`，不会写回客户端目录。

自定义位置：

```powershell
python dumate_login.py --from-desktop --output "D:\private\dumate-cookies" --verify
$env:DUMATE_COOKIE_FILE = "D:\private\dumate-cookies"
python dumate_daily.py
```

> `dumate-cookies`、`auth.json`、`.cookie-key`、HAR、运行日志都已被 `.gitignore` 覆盖。不要上传到 GitHub、网盘、群聊或截图。

---

<a id="quickstart"></a>
## 🚀 本地快速开始

```powershell
python -m pip install -r requirements.txt

$env:DUMATE_COOKIE = "bce-sessionid=<value>; bce-user-info=<value>"
python dumate_daily.py
```

多账号：

```powershell
$env:DUMATE_COOKIES = @"
账号一|bce-sessionid=<value>; bce-user-info=<value>
账号二|bce-sessionid=<value>; bce-user-info=<value>
"@
python dumate_daily.py
```

只查状态，不领取：

```powershell
python dumate_daily.py --query
```

只运行第二个账号：

```powershell
python dumate_daily.py --only 2
```

Linux / macOS：

```bash
python3 -m pip install -r requirements.txt
export DUMATE_COOKIE='bce-sessionid=<value>; bce-user-info=<value>'
python3 dumate_daily.py
```

---

<a id="qinglong"></a>
## 🐧 青龙面板部署

| 步骤 | 操作 |
| :---: | :--- |
| **1** | 依赖管理安装 `requests` 和 `cryptography`。 |
| **2** | 上传 `dumate_daily.py`。桌面登录导入可选上传 `dumate_login.py`。 |
| **3** | 环境变量新增 `DUMATE_COOKIES` 或 `DUMATE_COOKIE`。 |
| **4** | 新建定时任务，命令填 `task dumate_daily.py`。 |
| **5** | 建议北京时间每天 `00:13` 运行一次，避开整点高峰。 |

> 青龙任务优先使用 `task dumate_daily.py`，确保面板环境变量被注入。不要把多个账号拼成一个带引号的 JSON 字符串。

---

<a id="actions"></a>
## ☁️ GitHub Actions 部署

本仓库内置 [`.github/workflows/dumate.yml`](.github/workflows/dumate.yml)。

### 触发规则

| 事件 | 行为 |
| :--- | :--- |
| `push` 到 `main` | 运行 unittest、compileall 和 ruff。 |
| `schedule` | 每天先测试，再领取并上传 JSON 报告。 |
| `workflow_dispatch` | 手动执行同一套流程。 |

未配置 `DUMATE_COOKIES` / `DUMATE_COOKIE` 时，定时领取会输出明确的 SKIPPED notice 并成功结束；配置凭据后，脚本异常仍保持失败状态。

### Secrets

| Secret | 必填 | 值 |
| :--- | :---: | :--- |
| `DUMATE_COOKIES` | 二选一 | 多账号 Cookie，换行分隔。 |
| `DUMATE_COOKIE` | 二选一 | 单账号 Cookie。 |
| `PUSHPLUS_TOKEN` | ⬜ | PushPlus 推送。 |
| `BARK_URL` | ⬜ | Bark 推送地址。 |
| `WXPUSHER_APP_TOKEN` | ⬜ | WxPusher 应用令牌。 |
| `WXPUSHER_UID` | ⬜ | WxPusher 接收 UID，多个用逗号或空格分隔。 |
| `SERVERCHAN_SENDKEY` | ⬜ | Server酱 SendKey。 |
| `WECOM_WEBHOOK` | ⬜ | 企业微信群机器人 Webhook。 |
| `DINGTALK_WEBHOOK` | ⬜ | 钉钉群机器人 Webhook。 |
| `DINGTALK_SECRET` | ⬜ | 钉钉加签密钥。 |
| `DUMATE_WEBHOOK_URL` | ⬜ | 自定义 JSON Webhook。 |

### 内置定时

| 北京时间 | UTC cron | 说明 |
| :---: | :---: | :--- |
| 00:13 | `13 16 * * *` | 每天一次，避开整点高峰。 |

> GitHub `schedule` 使用 UTC，且属于 best-effort，可能延迟或被跳过。需要精确时间时使用青龙或外部调度。

---

<a id="cli"></a>
## ⌨️ 命令行与输出

```bash
python dumate_daily.py                 # 检查并领取
python dumate_daily.py --query         # 只查状态
python dumate_daily.py status          # 兼容位置参数写法
python dumate_daily.py --only 1        # 只运行第一个账号
python dumate_daily.py --no-notify     # 本次不推送
```

退出码：

| 退出码 | 含义 |
| :---: | :--- |
| `0` | 所有账号均为可信成功 |
| `1` | 至少一个账号失败或回读未确认 |
| `2` | 未配置凭据或配置格式错误 |

输出为 JSON Lines：每个账号一行，最后一行是汇总。

单账号结果字段：

| 字段 | 说明 |
| :--- | :--- |
| `account` | 掩码后的账号标签 |
| `result` | 结果码 |
| `ok` | 是否达到可信成功条件 |
| `before_has_issued` | 领取前是否已发放 |
| `after_has_issued` | 领取后是否已发放 |
| `bonus_points_before` | 领取前累计签到积分 |
| `bonus_points_after` | 领取后累计签到积分 |
| `credit` | 本次确认增加的签到积分 |
| `total_times` | 累计签到天数 |
| `quota_total` | 积分包总额 |
| `quota_used` | 已用积分 |
| `quota_remaining` | 剩余积分 |
| `quota_error` | 积分总览读取失败原因，不影响签到差额判定 |

---

## 🧭 结果码

| 结果码 | 是否成功 | 含义 |
| :--- | :---: | :--- |
| `CLAIMED` | ✅ | 本次领取已由状态翻转和正积分差额确认 |
| `ALREADY_CLAIMED` | ✅ | 运行前已领取 |
| `AVAILABLE` | ✅ | 查询模式确认可领取 |
| `AUTH_EXPIRED` | ❌ | Cookie 过期或接口返回登录页 |
| `CREDENTIAL_INCOMPLETE` | ❌ | 缺少领取所需的 `bce-user-info` |
| `CLAIM_NOT_APPLIED` | ❌ | 提交领取后仍未发放 |
| `CREDIT_UNCONFIRMED` | ❌ | 已发放但积分没有增加 |
| `STATUS_UNRECOGNIZED` | ❌ | 状态字段缺失或无法解析 |
| `RATE_LIMITED` | ❌ | HTTP 429 |
| `REDIRECT` | ❌ | 非登录页的 3xx 跳转 |
| `BUSINESS_ERROR` | ❌ | 服务端业务错误 |
| `HTTP_ERROR` | ❌ | 非 2xx HTTP 错误 |
| `NETWORK_ERROR` | ❌ | 网络异常 |
| `INVALID_JSON` | ❌ | 回包不是 JSON |
| `INVALID_RESPONSE` | ❌ | 回包不是 JSON 对象 |
| `CONFIG_ERROR` | ❌ | 环境变量、Cookie 或基址配置错误 |

---

<a id="success"></a>
## ✅ 成功判据

本项目不把“脚本跑了”“HTTP 200”“POST 返回成功”单独当成成功。

| 场景 | 必须满足 |
| :--- | :--- |
| 今日已领取 | 领取前 `hasIssued=true`，并成功读取签到信息 |
| 今日新领取 | POST 后 `hasIssued=true`，且 `totalPoints` 正差额大于 0 |
| 只查状态 | `hasIssued` 可明确解析 |

积分总览读取失败会记录为 `quota_error`，不会伪造余额；签到本身仍以 `loginBonusInfo` 的前后变化判定。

---

## 🧪 测试与静态检查

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
python -m ruff check dumate_daily.py dumate_login.py tests
```

测试全部使用 fake response / fake session：

- 已领取时跳过 POST；
- 未领取、POST、状态翻转、积分增加；
- POST 成功但状态未翻转；
- POST 成功但积分未增加；
- HTML 登录页、302 登录跳转、401；
- Cookie 引号与分号解析、CSRF 提取；
- 多账号隔离、手机号标签掩码、敏感值脱敏；
- 桌面 `auth.json` 的 AES-256-GCM 解密与域名过滤。

> 单测通过只证明代码路径正确，不代表某个真实账号今天已领取成功。真实结果必须由实际运行后的 `hasIssued` 和积分差额回读证明。

---

## 🧠 设计原则

- **协议先行**：先固定请求路径、请求体、状态字段和回读字段，再实现流程；
- **服务端回读**：新领取必须同时满足状态翻转和积分正差额；
- **账号隔离**：一个账号失败，不影响后续账号；
- **幂等优先**：已领取识别为中性成功，不重复 POST；
- **不掩盖失败**：状态不明、积分未增加、登录过期都单独报告；
- **最小暴露**：Cookie 只在内存和本地忽略文件中使用，不写日志和报告；
- **无自动兜底**：读取状态失败时不会盲目提交领取。

---

## 🔒 隐私说明

本仓库不包含任何账号、手机号、Cookie、Token、CSRF、设备号、认证文件或运行日志。所有凭据均由环境变量、GitHub Secrets 或你自己的本机忽略文件注入。

请勿提交：

- `~/.dumate-cookies`
- `*_cookies.json`
- `*_cookie.txt`
- `auth.json`
- `.cookie-key`
- `login_result.json`
- `dumate-report.json`
- `dumate-report.jsonl`
- 包含真实 Cookie、CSRF、手机号或积分流水的截图和日志

---

## 📁 目录结构

```text
DuMate-Daily/
├── .github/
│   └── workflows/
│       └── dumate.yml
├── assets/
│   ├── donate-alipay.jpg
│   └── donate-wechat.png
├── docs/
│   ├── README.en.md
│   ├── README.zh-Hant.md
│   ├── README.ja.md
│   ├── README.ko.md
│   └── README.pt-BR.md
├── tests/
│   ├── test_dumate_daily.py
│   └── test_dumate_login.py
├── dumate_daily.py
├── dumate_login.py
├── CHANGELOG.md
├── LICENSE
├── NOTICE.md
├── THIRD_PARTY_NOTICES.md
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 📦 版本与发布

- 当前版本：`v1.0.0`（2026-11-24）；
- 每次实质更新单独发布版本，历史版本保留；
- 公开包不得包含凭据、手机号、Cookie、CSRF、JWT、运行日志或本机路径。

下载页：<https://github.com/L0NE-6/DuMate-Daily/releases>

---

## ⚠️ 免责声明

本项目用于个人学习和合法的个人自动化。百度搭子的活动规则、接口、积分口径和账号资格由服务方决定；使用前请确认对应服务条款，并自行承担账号、网络、活动和接口变化带来的风险。

---

## ☕ 支持与投喂

脚本完全免费，无广告、无功能限制。如果它确实帮你省了时间，欢迎自愿赞赏；不影响任何功能，也不影响 Issue 响应。

<p align="center">
  <img src="assets/donate-wechat.png" width="260" alt="微信赞赏码" />
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <img src="assets/donate-alipay.jpg" width="260" alt="支付宝收款码" />
</p>
<p align="center"><sub>💚 微信支付（左） &nbsp;|&nbsp; 💙 支付宝（右）</sub></p>

> 收款码仅用于向作者自愿赞赏。任何第三方以代下载、代部署、内部资源或会员群为由收费，均与作者无关。禁止倒卖本项目。

---

## 💬 反馈与贡献

- [提交 Issue](https://github.com/L0NE-6/DuMate-Daily/issues)
- [发起 Pull Request](https://github.com/L0NE-6/DuMate-Daily/pulls)

反馈问题时，请附公开规则、脱敏后的请求/响应字段、运行结果和复现步骤。不要上传真实 Cookie、CSRF、手机号或完整账号日志。

---

<a id="star-trail"></a>
## ✦ 星轨 Star Trail

> 每一次 Star 都是一枚信号灯。这里记录 DuMate Daily 与社区一起走过的轨迹，也提醒我继续把自动化做得更稳、更透明。

<a href="https://star-history.com/#L0NE-6/DuMate-Daily&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=L0NE-6/DuMate-Daily&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=L0NE-6/DuMate-Daily&type=Date" />
    <img alt="DuMate Daily Star Trail" src="https://api.star-history.com/svg?repos=L0NE-6/DuMate-Daily&type=Date" />
  </picture>
</a>

---

<div align="center">
  <sub>L0NE-6 · DUMATE SIGNAL &nbsp;|&nbsp; 点个 <b>Star</b>，让下一次签到有迹可循 ✨</sub>
</div>
