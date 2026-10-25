# USER_GUIDE.md

Plain-language guide to what this system does, what it will never do, and the risk you
are accepting by running it.

## What it does every run

1. Reads your resume and `candidate_facts.yaml`.
2. Collects the newest relevant jobs from **LinkedIn** and **Naukri** in your own
   logged-in browser. (Job-alert email intake exists but is off by default —
   scoring runs on web-collected jobs only.)
3. Scores each job 0–100 against your resume with evidence.
4. Routes by **your exact rules**.
5. Keeps a ledger so it never applies or emails twice.
6. Emails you a summary and any job packets that need you.

## The 70/90 rules

| Match | What happens |
|---|---|
| **Below 70** | Discarded. No apply. No email. |
| **Above 90** | Sent to your inbox **even if Easy Apply exists**, for a human look. |
| **70 to 90** | **Auto-applied** when LinkedIn Easy Apply or Naukri in-platform Apply can submit and every required question has a stored answer. |
| **70 to 90, external site** | Emailed to you. It does **not** puppet Greenhouse/Lever/Workday. |
| **70 to 90, apply failed / captcha / missing fact** | Emailed to you, naming the missing field. Failed submits never vanish. |

Recency orders the auto-apply queue (a 6-hour-old 78 beats a 5-day-old 88 inside the
band), but never overrides the 70/90 cutoffs.

The digest carries the best packets first (score, then recency), capped at
`max_packet_emails_per_run` per section so it stays readable. Anything beyond the
cap is counted in the summary as queued and competes again tomorrow — nothing is
silently dropped, and nothing is ever emailed twice.

## What gets auto-applied vs emailed

- **Auto-applied:** in-platform applies scoring 70–90 with all form facts available.
- **Emailed (inbox):** everything above 90; every external-ATS job at 70+; every failed
  or incomplete apply.

## It will never

- Invent CTC, notice period, visa, years, or a "reason for change."
- Apply below 70 to hit a volume target.
- Submit a different person's resume.
- Solve or bypass a CAPTCHA or security checkpoint.
- Send your name, email, phone, PAN/Aadhaar, or company to a hosted model.
- Spend money. Not one rupee.

## Account-restriction risk (read this)

**This tool uses automation on LinkedIn and Naukri, and both prohibit that.**

- LinkedIn's "Prohibited software and extensions" help page says it does not permit
  third-party software, bots, plugins, or extensions that "scrape, modify the appearance
  of, or **automate activity**" on LinkedIn, and that violators "risk having their
  accounts restricted or shut down."
- Naukri's Terms prohibit automated crawling/scraping, accessing the site "except through
  the interfaces expressly provided," and imposing an unreasonable load.

You are running this on **your own accounts, on your own machine**, and the design keeps
volume low and human-paced. But the risk is **not zero** and this tool is **not
"undetectable" or "ToS-safe."** If either platform locks your account, **stop**. The next
step is lower volume or the mailbox-alert fallback — never a stealth tool.

## How to raise caps safely

Edit `config.yaml`:

- `search.daily_collection_cap_per_platform` (default 200)
- `apply.daily_auto_apply_cap_per_platform` (default 10)
- `apply.min_seconds_between_applies` (default 90)

Raise one at a time, watch for checkpoints for a few days, then raise again. Never run
overnight unattended; quiet hours are 22:30–08:00 by default. A run you start
yourself is attended by definition, so you can always override with
`python -m jobagent.cli run --force` (or `collect --force`) — the scheduled
tasks never pass that flag, so they stay quiet-hours-bound.

## How to add a new screening answer

1. Open `candidate_facts.yaml`.
2. Under `screening_answers`, add a line, e.g.:
   ```yaml
   screening_answers:
     comfortable_with_c2h: "yes"
     "are you open to contract roles": "yes"
   ```
3. Save. The autofill mapper picks it up on the next run. For a brand-new question type
   you can also add a rule in `jobagent/facts.py` `answer_for_question`.

## Turning on live submit

Live submit is **off by default** (`apply.live_submit_enabled: false`) and every run is a
dry run until:

1. Your golden set (`labels/golden_set.yaml`, 50+ labeled jobs) shows auto-apply
   precision **≥ 0.80** (`python -m jobagent.cli eval`).
2. You flip `live_submit_enabled: true`.

Then start with `daily_auto_apply_cap_per_platform: 3`, watch the first run, and raise
slowly.

## The three buckets, in one line each

- **A — go:** in-platform, 70–90, facts complete → auto-apply.
- **B — you:** above 90, or external, or incomplete/failed → email.
- **C — gone:** below 70 → ignored.