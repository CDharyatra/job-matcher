# RUNBOOK.md

Operational playbook. Symptoms → diagnosis → action. Everything here is $0.

---

## 1. First-time setup (one time)

1. `python -m jobagent.cli init` — creates dirs and `candidate_facts.yaml`.
2. Fill `candidate_facts.yaml` (see README). Copy `.env.example` → `.env` and add
   `NVIDIA_API_KEY` and the Gmail `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD`.
3. Create the **dedicated Chrome profile** and log in by hand (step 2 in README).
4. `python -m jobagent.cli doctor` — expect the `$0.00` audit and no problems.
5. `python -m jobagent.cli models` — confirm the free NVIDIA ids your key serves; write
   them into `docs/MODELS.md`.

## 2b. Rerank API keys (optional, all $0)

The cross-encoder rerank layer tries providers in `config.yaml` order and skips
any without a key — nothing breaks if you add none (the local model covers it).

- **Jina** (primary hosted rerank): sign up at https://jina.ai/, copy the API key
  from the dashboard, paste as `JINA_API_KEY=` in `.env`. Free quota is about
  10M tokens at 100 requests/minute — far beyond this pipeline's needs.
- **Voyage** (backup): https://docs.voyageai.com/ → API keys → `VOYAGE_API_KEY=`.
  About 200M tokens free one-time.
- **Cohere** (audit reserve): https://cohere.com/ → trial key → `COHERE_API_KEY=`.
  Only ~1,000 calls/month, so it sits last in the chain by design.
- **local_bge** (no key ever): `pip install torch --index-url
  https://download.pytorch.org/whl/cpu` then `pip install -e ".[local]"`.
  Weights (~2.3 GB) download once from Hugging Face on first use.

After adding a key, run `doctor` (it lists `rerank:<provider>: present`) and watch
for `rerank jina/... score=...` lines in the next run's log.

## 3. Gmail app password

1. Google Account → Security → turn on **2-Step Verification**.
2. Create an **App password** (16 chars). Put it in `.env` as `GMAIL_APP_PASSWORD`.
3. In Gmail, create a label **JobAlerts** and a filter that routes LinkedIn/Naukri alert
   mail there. The reader pulls only that folder.
4. If you hit "Too many login attempts", wait, then regenerate the app password.

## 3. Dedicated Chrome profile

Chrome 136+ ignores remote debugging on the **default** profile, and the default profile
is locked while Chrome runs. Do **not** point the tool at your normal profile.

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="C:\easy tool\job-search-agent\.browser\profile"
```

Log into LinkedIn and Naukri in that window, once. Leave it running. The tool attaches
over CDP. If you close that Chrome, the next run relaunches it (same profile = still
logged in).

## 4. `429` from NVIDIA

Symptom: `rate limited on nvidia/...`, judge scores stop appearing.
- Confirm `llm.enabled: true` and the key is valid (`cli models`).
- The adapter already backs off and fails over down `judge_chain`. To reduce pressure:
  lower `llm.daily_call_budget_per_model`, raise `scoring` prefilter (`PREFILTER_FLOOR`),
  or add a zero-retention Zen/OpenRouter `:free` model to the chain.
- Deterministic scoring still runs. The run never stops.

## 5. Session dead / wedged Chrome

Symptom A: `cannot attach to chrome ... Timeout exceeded` even though something
listens on the debugging port. The dedicated Chrome is half-dead (seen after an
out-of-memory episode): kill only that instance and relaunch it —

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -like '*remote-debugging-port=9222*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

then relaunch per §3 and re-run. Your normal Chrome is untouched by this
(the filter matches only the debugging-port instance).

Symptom B: `SessionDeadError: linkedin: not logged in`.
- First diagnose without scraping anything: `python -m jobagent.cli browser`.
  It attaches to the dedicated Chrome and prints `LOGGED IN` / `NOT LOGGED IN` /
  `CHECKPOINT` per platform, with the actual page URL.
- If `NOT LOGGED IN`: reopen the dedicated Chrome profile window and log in again.
- Re-run. If it recurs, the platform is asking for a checkpoint → see §6.

## 6. Checkpoint / CAPTCHA

Symptom: `CheckpointError`, or a job returns `detail=checkpoint`.
- The tool **does not** solve or bypass it. That job goes to the inbox.
- If it repeats, the platform pauses for the day (by design). Lower
  `daily_*_cap_per_platform` and `daily_auto_apply_cap_per_platform`.
- Fall back to alert-email intake: job collection still works with the browser off.

## 7. Missing CTC or notice period

Symptom: a job returns `missing facts: compensation.notice_period_days` and is emailed.
- Expected behavior. Paste the value into `candidate_facts.yaml` once.
- For an immediate fix: edit the file, then re-run; the job is not marked applied, so it
  will be reconsidered.

## 8. Empty search feed

Symptom: `linkedin collected 0 jobs`.
- LinkedIn is migrating its job search UI and filters change. Check
  `jobagent/browser/selectors.py` against the live page and update the card selector.
- Widen `search.date_posted_ladder_hours` and `search.locations`.
- Confirm the dedicated profile is actually logged in.

## 9. Free model disappeared

Symptom: `all models exhausted -> deterministic only`.
- `cli models` to list what the key serves now.
- Update `config.yaml` `judge_chain`/`classify_chain` and `docs/MODELS.md`. Never add a
  paid id — `policy.assert_free` will refuse it anyway.

## 10. Gmail send fails

- Check `GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD`. App passwords require 2FA.
- Stay under 500 recipients/day (personal Gmail). The digest is one message to you.
- If Gmail blocks sign-in, regenerate the app password.

## 11. Daily schedule

```
python -m jobagent.cli schedule            # print the schtasks commands
python -m jobagent.cli schedule --install  # create them
```
Tasks run `python -m jobagent.cli run` (dry-run unless live is enabled).

## 12. Turning on live submit (only after the gate)

1. Build `labels/golden_set.yaml` with 50+ labeled jobs.
2. `python -m jobagent.cli eval` → require **precision ≥ 0.80**.
3. Set `apply.live_submit_enabled: true` in `config.yaml`.
4. First live run with caps low (`daily_auto_apply_cap_per_platform: 3`) while you watch.
5. Raise caps gradually. Never run overnight.