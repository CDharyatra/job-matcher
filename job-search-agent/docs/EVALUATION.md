# EVALUATION.md

What "good" means, how it is measured, and the gate that keeps live submit off.

## 1. The quality bar

- A **70** means the person on the resume could credibly **do** the job as written.
  Not "could learn it." Not "the title says Engineer."
- **Above 90** must be **rare**. If half the feed scores above 90, the scorer is broken.
- **No evidence, no match.** Every routing-affecting score carries an evidence list
  mapping a job requirement to a resume signal.
- A **must-have miss hard-caps** the score below 70. A Python-only resume never
  auto-applies to a Java-only posting.

## 2. Golden set

`labels/golden_set.yaml` holds 50+ real jobs, each with a human label:
`apply`, `inbox`, or `discard`. Build it by hand from real postings you have seen.

```
python -m jobagent.cli eval
```

Reports: total jobs, how many the system would auto-apply, how many of those match the
human `apply` label, and the resulting **precision**.

## 3. The gate

```
precision = correct_auto_applies / predicted_auto_applies
```

- **Live submit stays frozen until precision ≥ 0.80.**
- Config: `apply.precision_gate: 0.80` and `apply.live_submit_enabled: false`.
- Until then every run is a **dry run**: it scores, writes what it *would* have applied,
  and emails those as dry-run packets. `record_application(..., "would_apply_dryrun")`.

## 4. What the tests cover (all mocked, no network, no browser)

| Area | Test file |
|---|---|
| Salary parsing (LPA, USD, not disclosed) | `test_textutil.py` |
| Relative dates, years bands, skill aliases/boundaries | `test_textutil.py` |
| Routing exact 70/90 rules incl. boundaries | `test_routing.py` |
| Dedup across LinkedIn vs Naukri | `test_dedup.py` |
| Facts → screening question mapping; missing-fact behavior | `test_facts_autofill.py` |
| Deterministic scorer + hard caps | `test_scoring.py` |
| Matcher fusion, invalid-evidence rejection, over-optimism tempering | `test_matcher.py` |
| $0 policy, paid refusal, PII redaction | `test_llm_policy_redact.py` |
| Idempotency (no double apply / double email) | `test_idempotency.py` |
| Email/alert parsing + digest rendering | `test_email_alerts.py` |
| Security: no paid APIs, no hardcoded keys, gitignore | `test_security.py` |
| Pipeline dry-run + idempotency | `test_pipeline.py` |
| Resume PDF/DOCX parse | `test_resume.py` |

Run: `python -m pytest -q`.

## 5. Failure-mode tests (manual, against the real system)

- **Session dead:** run with the dedicated Chrome logged out → expect `SessionDeadError`
  and no crash.
- **429 storm:** temporarily set a tiny `daily_call_budget_per_model`, run → expect a
  failover then deterministic-only, and the run still completes.
- **Empty feed:** point at a location with no jobs → expect zero collected and a summary
  email.
- **Malformed date:** feed a job with `posted_at: "soon"` → expect `None`, not a crash.

## 6. Comparing deterministic vs LLM

`eval` runs with the configured judge. Re-run with `llm.enabled: false` and compare the
precision. If the deterministic-only precision is higher, **trust the deterministic
scorer and email instead of auto-applying** — and record that finding here.