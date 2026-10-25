# COST.md — proof of $0.00

Every dependency is either free/open-source, OS-bundled, or a free endpoint on an
already-owned key with no credit card and no auto-charge. No row below has a dollar price.

---

## 1. Software & runtime

| Component | Cost | Basis |
|---|---|---|
| Windows 11 Home | $0 (pre-owned) | OS already installed; Task Scheduler bundled |
| Python 3.13 | $0 | Already installed |
| sqlite3 | $0 | Python stdlib, public domain |
| pdfplumber | $0 | MIT |
| python-docx | $0 | MIT |
| pypdf (fallback) | $0 | BSD |
| Playwright for Python | $0 | Apache-2.0 (drives existing Chrome, no cloud) |
| Gmail (personal @gmail.com) | $0 | Pre-existing personal account |
| **Subtotal** | **$0.00** | |

## 2. Inference

| Endpoint | Cost | Card? | Basis |
|---|---|---|---|
| NVIDIA NIM free endpoints | $0 | No card on file required by design | User's existing trial key; `integrate.api.nvidia.com/v1` |
| OpenCode Zen free models | $0 | Only if the user already has a Zen key | Only ids priced "Free" are configured |
| OpenRouter `:free` models | $0 | No | Backup judge only |
| Groq free plan | $0 | No | Backup judge only |
| Deterministic scorer | $0 | — | Pure local code, always-on fallback |
| **Subtotal** | **$0.00** | | |

**Guards:** a paid-model blocklist in `jobagent/llm/policy.py`; a unit test greps the whole
repo for banned providers/prices; the adapter refuses any model id not on the free allowlist.

## 3. Email

| Use | Cost | Basis |
|---|---|---|
| Send (SMTP `smtp.gmail.com:587`) | $0 | Gmail app password |
| Receive (IMAP `imap.gmail.com:993`) | $0 | Gmail app password |
| Limits | — | ≤500 recipients/day, ≤500 per message (personal Gmail) |
| **Subtotal** | **$0.00** | |

## 4. Job data

| Item | Cost | Basis |
|---|---|---|
| LinkedIn collection | $0 | User's own logged-in browser session |
| Naukri collection | $0 | User's own logged-in browser session |
| Job-alert email intake | $0 | Mailbox the user already has |
| Job datasets / scraping APIs | **not used** | Would cost money |
| **Subtotal** | **$0.00** | |

## 5. Infrastructure

| Item | Cost | Basis |
|---|---|---|
| Local machine (always-on) | $0 | Pre-owned hardware |
| Scheduler | $0 | Windows Task Scheduler |
| Storage | $0 | Local SQLite file |
| Hosting | none | Runs locally; dashboard on 127.0.0.1 only |
| **Subtotal** | **$0.00** | |

---

## 6. Explicitly forbidden (never added)

Paid LLMs (Anthropic, OpenAI, Google paid, xAI, Groq paid, OpenRouter paid, Together paid,
Fireworks paid), **paid OpenCode Zen models** (`muse-spark-1.3`, Claude, GPT, Gemini,
DeepSeek billed, Kimi billed, GLM billed, Grok billed), paid apply bots / extensions
(Resumly, Linked Helper), paid job APIs, paid ATS submit APIs, paid proxies/captcha farms,
paid VPS/serverless/Postgres, paid email vendors (SendGrid, SES, Mailgun, Resend, Postmark),
and anything that asks for a credit card.

## 7. Ongoing risk of cost

The only endpoint that could theoretically bill is NVIDIA trial if the user separately buys
credits. The tool never enables billing and only calls the free build.nvidia.com endpoints on
the user's existing key. If NVIDIA begins requiring payment, calls fail with 4xx, the adapter
degrades to another `$0` model, then to the deterministic scorer — **it never falls back to a
paid call.**

## 8. Verification

`python -m jobagent.cli doctor` prints a cost audit: every configured provider endpoint,
model id, and a `paid_api_scan` result (greps the repo and config for banned names). Expected
output ends with:

```
COST AUDIT: $0.00/month  —  paid providers configured: 0
```

---

**Total monthly cost: $0.00. One-time cost: $0.00. Credit card required: No.**