# jobagent — a local, $0.00 job-search operating system

A single-user tool that collects the newest relevant jobs from **LinkedIn** and
**Naukri**, scores them against your resume, **auto-applies** when your 70/90 rules say
apply, and **emails** when they say email. It runs on your machine, in your own logged-in
browser, on your own accounts, and it costs **nothing**.

It is not a copilot that only sends links. It collects, scores, applies, and reports.

> **Read `docs/USER_GUIDE.md` before enabling live submit.** Both platforms prohibit
> automation. This tool keeps volume low and human-paced, but the account risk is real
> and it is **not** undetectable.

---

## What you need (all free)

- Windows 10/11 with **Python 3.11+** (tested on 3.13) and **Google Chrome**.
- Your **resume** (PDF or DOCX) and a filled **`candidate_facts.yaml`**.
- An **NVIDIA API key** (free trial) — optional but recommended; without it the tool runs
  **deterministic-only** and still works.
- A **Gmail** account with a 16-character **app password** (needs 2-Step Verification).
- No credit card anywhere.

See `docs/COST.md` for the full $0 proof.

---

## Install

```powershell
cd "C:\easy tool\job-search-agent"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m jobagent.cli init
```

`init` creates `candidate_facts.yaml` from the template.

## Configure

### 1. Fill `candidate_facts.yaml`

Open it and fill what you can. Blank is allowed but means "unknown": if an application
asks for a blank field, the tool **stops that application, marks it failed, and emails
you naming the field**. It never guesses. Key fields for the 70/90 flow:

- current CTC, expected CTC (+ floor), notice period, serving notice, last working day
- total years, current city, relocation cities, work authorization
- `application.resume_files[].path` → point to your resume PDF/DOCX

Configurable behavior lives in `config.yaml` (titles, skills, locations, caps,
thresholds). Nothing secret there.

### 2. Create `.env`

```powershell
Copy-Item .env.example .env
```
Then edit `.env`:
```
NVIDIA_API_KEY=nvapi-...
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
```

### 3. Set up the dedicated Chrome profile (important)

Chrome 136+ ignores remote debugging on your **default** profile, and the default profile
locks while Chrome is open. Use a dedicated profile:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="C:\easy tool\job-search-agent\.browser\profile"
```

Log into **LinkedIn** and **Naukri** in that window, once. The tool attaches over CDP.
Same machine, same human, real session — no cookies copied anywhere.

### 4. Connect Gmail alert intake (optional but recommended)

Create a Gmail label **JobAlerts** and a filter routing LinkedIn/Naukri job-alert emails
there. When a live session is challenged, the tool falls back to this mailbox.

---

## Use

```powershell
.\.venv\Scripts\python.exe -m jobagent.cli doctor     # cost + secret + config audit
.\.venv\Scripts\python.exe -m jobagent.cli models     # confirm free model ids your key serves
.\.venv\Scripts\python.exe -m jobagent.cli resume     # parse resume -> profile
.\.venv\Scripts\python.exe -m jobagent.cli intent     # preview search queries
.\.venv\Scripts\python.exe -m jobagent.cli collect    # read-only collection (no apply)
.\.venv\Scripts\python.exe -m jobagent.cli run        # full pipeline, DRY RUN by default
.\.venv\Scripts\python.exe -m jobagent.cli eval       # golden-set precision gate
```

`run` is always a **dry run** until you set `apply.live_submit_enabled: true` in
`config.yaml`, which you should only do after `eval` shows precision **≥ 0.80** on a
50+ job golden set (`labels/golden_set.yaml`).

### Schedule it (free, OS-bundled)

```powershell
.\.venv\Scripts\python.exe -m jobagent.cli schedule            # show the commands
.\.venv\Scripts\python.exe -m jobagent.cli schedule --install  # create the tasks
```

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

All tests are mocked — no network, no browser, no paid calls.

---

## Docs

| File | What |
|---|---|
| `docs/RESEARCH.md` | primary-source research + disagreements with the brief |
| `docs/MODELS.md` | chosen $0 model ids + routing + privacy gate |
| `docs/COST.md` | proof that everything is $0.00 |
| `docs/ARCHITECTURE.md` | layers, data flow, invariants, module map |
| `docs/RUNBOOK.md` | 429s, session dead, missing CTC, empty feed, checkpoints |
| `docs/EVALUATION.md` | the 80% precision gate and what the tests cover |
| `docs/USER_GUIDE.md` | the 70/90 rules, account risk, how to raise caps |

---

## The three layers

- **Intelligence** — resume + facts understanding, intent expansion, hybrid 0–100
  matching with evidence.
- **Action** — logged-in LinkedIn/Naukri collection, auto-apply for the 70–90 band,
  inbox for above-90/external/failed.
- **Memory** — SQLite ledger (no double apply, no double email), daily summary email,
  local logs.

## Safety guarantees

- Own accounts only. No credential sharing. No fake profiles.
- Never stores LinkedIn/Naukri passwords; uses your logged-in browser session.
- Never bypasses CAPTCHAs or checkpoints — it stops and emails.
- Never sends PAN/Aadhaar/bank/passwords anywhere, and redacts PII before any cloud call.
- Never uses a paid model or service; `doctor` audits for it.

## Cost

**$0.00/month. One-time: $0.00. Credit card: no.**