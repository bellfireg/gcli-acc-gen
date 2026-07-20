# 🤖 gcli-acc-gen

**Grok CLI account generator** — fully automated end-to-end pipeline that creates Grok (accounts.x.ai) accounts and registers them to [9Router](https://github.com/nicepkg/9router) via OAuth device flow.

Zero manual steps. Scalable to N accounts.

---

## 🎯 What it does

1. **Generates temp email** via Cloudflare Worker (catch-all on your domain)
2. **Signs up at accounts.x.ai** — fills email, auto-submits OTP
3. **Solves Cloudflare Turnstile** on "Complete your sign up" screen via [2captcha](https://2captcha.com)
4. **Fills name + password** → account created with valid credentials
5. **Triggers 9Router device-code flow** for `grok-cli` provider
6. **Authorizes via browser** — logs in with the new account, clicks Allow
7. **9Router auto-stores** OAuth tokens (accessToken + refreshToken)

Output: `accounts.json` with `{email, password, session_cookies, status}` per account.

---

## 📋 Prerequisites

### 1. Residential IP (REQUIRED)

Grok blocks datacenter IPs with a Cloudflare challenge page. You **must** run this on a residential connection (home ISP, mobile hotspot, residential proxy). VPS/datacenter will not work.

### 2. Cloudflare account + custom domain

For the temp email catch-all worker. Free tier works.

### 3. 2captcha account

For solving Cloudflare Turnstile. Cost: ~$0.002/solve. Balance starts at $1.
- Sign up: https://2captcha.com
- Get API key (32 chars, v1 API)

### 4. 9Router instance (optional)

Only needed if you want `--register-9router` (auto OAuth registration). Without it, the bot still creates accounts and saves them to `accounts.json`.

---

## 🚀 Setup

### Step 1: Deploy the email worker

You need a Cloudflare Worker that catches all email to `*@yourdomain.com` and exposes an HTTP API to mint addresses + read inbox.

**Option A: Use the companion repo [`cf-acc-gen`](https://github.com/bellfireg/cf-acc-gen)** which includes the worker code + deploy script.

**Option B: Manual setup** — deploy a worker with these endpoints (all gated by `/<SECRET>/api/...`):

| Endpoint | Method | Auth | Returns |
|----------|--------|------|---------|
| `/<SECRET>/api/new_address` | POST | none | `{address, jwt, domain}` |
| `/<SECRET>/api/parsed_mails` | GET | `Authorization: Bearer <address>` | `[{id, subject, from, ...}]` |
| `/<SECRET>/api/parsed_mail/<id>` | GET | `Authorization: Bearer <address>` | `{html, text, subject}` |
| `/<SECRET>/api/domains` | GET | none | `{domains: ["yourdomain.com"]}` |

Then enable Cloudflare Email Routing with a catch-all rule → forward to worker.

**Save the `API_SECRET`** (the path prefix) — you'll need it for `CF_MAILBOX_SECRET`.

### Step 2: Install gcli-acc-gen

```bash
git clone https://github.com/bellfireg/gcli-acc-gen.git
cd gcli-acc-gen
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Step 3: Install Camoufox browser

```bash
python -m camoufox fetch
```

This downloads the anti-detect Firefox binary (~100MB).

### Step 4: Configure environment

```bash
cp .env.example .env
# Edit .env with your values:
#   CF_MAILBOX_SECRET  — your worker's API_SECRET
#   WORKER_URL         — your worker URL
#   TWOCAPTCHA_KEY     — your 2captcha API key (32 chars)
#   NINEROUTER_PASSWORD — your 9Router admin password (optional)
```

Or put the 2captcha key in `~/.2captcha_key`:
```bash
echo -n "your_32_char_key" > ~/.2captcha_key
chmod 600 ~/.2captcha_key
```

---

## 🏃 Usage

### Generate N accounts (E2E: signup + 9Router registration)

```bash
# Load env vars
set -a; source .env; set +a

# Generate 10 accounts end-to-end
DISPLAY=:0 python -m grok_autopilot -n 10 --mail cloudflare --register-9router
```

### Generate accounts only (skip 9Router)

```bash
DISPLAY=:0 python -m grok_autopilot -n 5 --mail cloudflare
```

### Register existing accounts to 9Router only

If you already have accounts in `accounts.json` and just want to register them:

```bash
DISPLAY=:0 python -m grok_autopilot.ninerouter_grok --accounts accounts/accounts.json
```

### Headless mode (no browser UI)

```bash
DISPLAY=:0 python -m grok_autopilot -n 3 --mail cloudflare --headless
```

⚠️ Headless may trigger more bot detection. Recommended: headed on a box with X server.

---

## 📊 Output

`accounts/accounts.json`:

```json
[
  {
    "email": "abc1234567890def@yourdomain.com",
    "password": "RandomStrongPw!1A",
    "mail_jwt": "abc1234567890def@yourdomain.com",
    "session_cookies": {"cookies": [...], "localStorage": {...}},
    "created_at": 1784540880.0,
    "status": "password_set",
    "notes": "final_url=https://accounts.x.ai/account"
  }
]
```

Status values:
- `password_set` ✅ — account created with valid password, ready for 9Router
- `verified` ✅ — email verified but no password set (rare)
- `partial` ⚠️ — signup incomplete
- `failed` ❌ — error during creation

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Bot (Camoufox on residential box)                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 1. Mint temp email via CF Worker                    │   │
│  │ 2. Sign up at accounts.x.ai                         │   │
│  │ 3. Poll worker inbox for OTP (alphanumeric XXX-XXX) │   │
│  │ 4. Type OTP → auto-submit to Complete sign up       │   │
│  │ 5. Fill givenName, familyName, password             │   │
│  │ 6. Intercept turnstile.render (monkey-patch)        │   │
│  │ 7. Solve Turnstile via 2captcha (v1 API)            │   │
│  │ 8. Inject token via callback                        │   │
│  │ 9. Submit "Complete sign up"                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 10. Trigger 9Router device-code (GET /api/oauth/    │   │
│  │     grok-cli/device-code)                           │   │
│  │ 11. Open verification_uri_complete in browser       │   │
│  │ 12. Continue → Login with email + password          │   │
│  │ 13. Enter login OTP (fresh alphanumeric)            │   │
│  │ 14. Click Allow                                    │   │
│  │ 15. 9Router auto-polls + stores OAuth tokens        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 How Turnstile solving works

xAI's signup uses Cloudflare Turnstile on the "Complete your sign up" screen. We solve it via 2captcha:

1. **Before page load**, inject a script that monkey-patches `window.turnstile.render(container, params)`.
2. When xAI calls `turnstile.render(...)`, our patched version captures `params.sitekey`, `params.action`, `params.cData`, and `params.callback` into `window.__captcha_data`.
3. We send the sitekey to 2captcha's `in.php` endpoint (v1 API, `method=turnstile`).
4. Poll `res.php` until the token is ready.
5. Call `window.__captcha_callback(token)` — the captured callback — which tells the Turnstile widget the challenge is solved.
6. Also set the hidden `cf-turnstile-response` input as a fallback.

Reference: [2captcha Turnstile docs](https://2captcha.com/api-docs/cloudflare-turnstile)

---

## ⚠️ Important notes

- **Residential IP required.** Datacenter IPs get blocked at the Cloudflare edge.
- **Rate limits.** Grok may rate-limit signups from the same IP. The bot has a 30s cooldown between accounts; bump it if you hit limits.
- **2captcha key must be v1-compatible.** Some keys only work with v2 (`createTask`). Test with `curl "https://2captcha.com/res.php?key=YOUR_KEY&action=getbalance&json=1"`.
- **Email worker MINTED pattern.** The worker only accepts 16-char alphanumeric localparts. Don't hand-craft addresses — always mint via `/api/new_address`.
- **OTP format.** Grok sends alphanumeric codes like `S23-XSW` in the email subject. The bot strips the hyphen → `S23XSW` to match the form's `^[a-zA-Z0-9]+$` pattern.
- **OneTrust cookie consent.** Blocked at network level. The bot also nukes the SDK from DOM if it slips through.

---

## 🧪 Testing

```bash
python -m pytest tests/ -v
```

Self-checks cover OTP regex extraction (alphanumeric subject format, placeholder skip, etc).

---

## 📁 Project structure

```
gcli-acc-gen/
├── src/grok_autopilot/
│   ├── cli.py              # Entry point: -n N --register-9router
│   ├── register.py         # Signup + name/password/Turnstile flow
│   ├── ninerouter_grok.py  # 9Router device-code + browser authorize
│   ├── captcha/
│   │   └── turnstile.py    # 2captcha solver + render interceptor
│   ├── browser/
│   │   └── camoufox.py     # Anti-detect browser launcher
│   ├── infra/
│   │   └── temp_mail.py    # Cloudflare/MailTm providers
│   └── utils/logger.py
├── tests/
│   └── test_otp_extraction.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 🤝 Companion repo

- **[`cf-acc-gen`](https://github.com/bellfireg/cf-acc-gen)** — Cloudflare account generator + email worker. The email worker in that repo is what `gcli-acc-gen` uses for temp mailboxes.

---

## 📜 License

MIT — see [LICENSE](LICENSE).

---

## ⚖️ Disclaimer

For legitimate capability testing of trial accounts only. Don't use this to abuse free tiers at scale or violate xAI's Terms of Service. The authors are not responsible for misuse.
