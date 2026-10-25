# ARCHITECTURE.md

Three layers, all local, all $0.00.

```
                 +-------------------------------------------+
                 |            jobagent (CLI)                 |
                 |  init doctor models resume intent collect |
                 |  run [--live]  eval  schedule             |
                 +-------------------------------------------+
                                    |
         +--------------------------+---------------------------+
         |                          |                           |
   [ Layer 1 Intelligence ]   [ Layer 2 Action ]          [ Layer 3 Memory ]
   resume.py                  browser/linkedin.py         database.py (SQLite)
   facts.py                   browser/naukri.py           ledger + scores
   intent.py                  mail/alerts.py (fallback)    runs + llm_usage
   scoring.py                 autofill.py                 digest.py -> email
   matcher.py                 pipeline.py
   llm/* (judge, redact)
```

## Data flow of one run

1. **Ingest** — `resume.load_or_build()` parses PDF/DOCX (two-column aware), caches a
   profile JSON. `facts.load_facts()` loads `candidate_facts.yaml`. Facts win for form
   fields; resume wins for matching.
2. **Intent** — `intent.build_queries()` expands target titles into synonyms, adds
   skills/locations, and appends a remote query.
3. **Collect** — `browser.session.BrowserSession` attaches to the user's dedicated,
   manually-logged-in Chrome over CDP. `linkedin.collect()` and `naukri.collect()` walk
   filtered search pages with the recency ladder (24h → 48h → 7d), low page caps, and
   human pacing. If the browser is challenged/unavailable, `mail.reader` +
   `mail.alerts` parse job-alert emails as the fallback intake. **Collection never
   throws away a run.**
4. **Clean** — `models.Job.compute_dedup_key()` dedups by company + normalized title +
   city across platforms. `clean.is_blocklisted()` and `is_obvious_spam()` drop noise.
5. **Score** — `scoring.score_deterministic()` always runs (title synonyms, must-have
   coverage with hard cap, years band, location, recency, salary vs floor). Only
   survivors at/above `PREFILTER_FLOOR` and without a hard cap get one cached LLM judge
   call (`matcher.match_job`) with PII redacted first. The judge's JSON is validated; a
   missing/must-have miss above 55 or absent evidence is rejected. Fusion tempers
   over-optimism in both directions.
6. **Route** — `clean.route()` applies the exact 70/90 rules:
   - `< 70` → discard (no apply, no email).
   - `> 90` → inbox even if Easy Apply exists.
   - `70..90` **and** in-platform apply → auto-apply bucket.
   - `70..90` external / missing fact / checkpoint / error → inbox.
7. **Act** — `pipeline._apply()` opens the official modal and `autofill` fills only
   stored facts. A blank critical fact fails that job and names the field. Checkpoints
   stop that job (and pause if repeated) — never bypassed.
8. **Email** — `digest.build_digest()` renders above-90 packets, 70+ external packets,
   and failed-apply packets; `mail.sender.Mailer` sends via Gmail app password.
9. **Remember** — every job, score, application, and event is written to SQLite. The
   `ledger` table is the idempotency guard: no double apply, no double email. Dry-run
   writes a `dryrun` event that does **not** block a later live run.

## Key invariants

- **$0 only.** `llm.policy.assert_free()` refuses any non-allowlisted provider/model.
  `cli doctor` scans config for banned ids/services.
- **No invented facts.** `facts.Facts.answer_for_question()` returns `(None, key)` for
  known-but-blank fields; the apply layer fails that job and reports the key.
- **No PII to the cloud.** `llm.redact` strips name/email/phone/URLs/PAN/Aadhaar/CTC
  before every hosted call; NVIDIA trial endpoints are never sent raw PII.
- **Never bypass a wall.** `browser.session.detect_checkpoint()` raises instead of
  solving; the run stops or emails.
- **Degrade, don't die.** Browser down → alert-email intake. LLM down → deterministic
  scorer. Free endpoint 429 → failover down the chain → deterministic.

## Module map

| File | Responsibility |
|---|---|
| `jobagent/config.py` | Typed config from `config.yaml` + `.env` |
| `jobagent/models.py` | `Job` domain model + dedup key |
| `jobagent/textutil.py` | salary/date/years parsing, skill aliases, title expansion |
| `jobagent/facts.py` | facts tree, critical-field checks, question→fact mapping |
| `jobagent/resume.py` | PDF/DOCX extraction + profile build/cache |
| `jobagent/intent.py` | search-query expansion |
| `jobagent/scoring.py` | deterministic 0-100 scorer with hard caps |
| `jobagent/matcher.py` | deterministic + LLM fusion |
| `jobagent/clean.py` | blocklist, spam, dedup context, 70/90 routing |
| `jobagent/autofill.py` | screening question → fact → form fill |
| `jobagent/llm/*` | $0 policy, redaction, prompts, OpenAI adapter, cache/budget |
| `jobagent/browser/*` | CDP session, pacing, selectors, LinkedIn, Naukri |
| `jobagent/mail/*` | IMAP reader, alert parser, SMTP sender |
| `jobagent/pipeline.py` | orchestration |
| `jobagent/database.py` | SQLite store + ledger |
| `jobagent/digest.py` | packet/digest HTML |
| `jobagent/evaluate.py` | golden-set precision gate |
| `jobagent/scheduler.py` | Task Scheduler plan/install |
| `jobagent/cli.py` | entry points |