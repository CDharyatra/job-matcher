"""End-to-end pipeline: collect -> clean -> score -> route -> apply/dry-run -> email.

Degrades gracefully: if the browser is unavailable, uses job-alert email intake;
if the LLM is unavailable, uses the deterministic scorer; never pays, never stops
silently, always writes to the ledger.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from . import paths
from .autofill import Autofill
from .clean import (
    BUCKET_APPLY, BUCKET_DISCARD, BUCKET_INBOX,
    is_blocklisted, is_obvious_spam, route,
)
from .config import Config, load_config
from .database import Store
from .digest import build_digest, prioritize
from .facts import Facts, load_facts
from .intent import build_queries
from .llm.adapter import LLMClient
from .llm.policy import PaidModelError
from .logging_setup import get_logger, setup_logging
from .mail.sender import Mailer
from .matcher import MatchResult, match_job
from .models import Job, job_from_row
from .resume import load_or_build

log = get_logger("jobagent.pipeline")


def _resume_paths(facts: Facts) -> list[str]:
    files = facts.application.get("resume_files") or []
    return [f.get("path", "") for f in files if isinstance(f, dict)]


LOCK_MAX_AGE_HOURS = 6


def _lock_path() -> "Path":
    from . import paths
    return paths.DATA_DIR / ".run.lock"


def acquire_run_lock(run_id: str) -> bool:
    """Atomic single-run guard. True if this process owns the lock.

    Uses O_CREAT|O_EXCL so two processes started the same second cannot both
    win. A lock older than LOCK_MAX_AGE_HOURS is treated as stale (e.g. after
    Ctrl+C, which never releases it) and replaced.
    """
    import json
    import os
    import time
    from . import paths
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = _lock_path()
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age_h = (time.time() - lock.stat().st_mtime) / 3600
            if age_h < LOCK_MAX_AGE_HOURS:
                return False
        except OSError:
            return False
        lock.unlink(missing_ok=True)
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "pid": os.getpid(),
                   "started_at": time.time()}, f)
    return True


def release_run_lock() -> None:
    try:
        _lock_path().unlink(missing_ok=True)
    except OSError:  # noqa: BLE001
        pass


def platform_order(cfg: Config, only: list[str] | None = None) -> list[str]:
    """Collection order from config (`platforms.order`), optionally restricted
    to one platform via --platform. Unknown names are ignored."""
    order = list((cfg.platforms or {}).get("order") or ["linkedin", "naukri"])
    if only:
        keep = {p.lower() for p in only}
        order = [p for p in order if p in keep]
    return [p for p in order if p in ("linkedin", "naukri")]


class Pipeline:
    def __init__(self, cfg: Config | None = None, store: Store | None = None):
        self.cfg = cfg or load_config()
        self.store = store or Store(self.cfg.storage.sqlite_path)
        self.facts = load_facts()
        self.resume = load_or_build(_resume_paths(self.facts))
        self.llm = LLMClient(self.cfg, self.store)
        from .llm.redact import build_redactor
        self.llm.set_redactor(build_redactor(self.facts))
        from .llm.rerank import RerankClient
        self.rerank = RerankClient(self.cfg, self.store)
        self.autofill = Autofill(self.facts, self.llm)
        self.mailer = Mailer()

    # ---- collection -------------------------------------------------------
    def collect(self, queries, run_id: str, only: list[str] | None = None) -> list[Job]:
        jobs: list[Job] = []
        platforms = self.cfg.platforms or {}
        want = {p.lower() for p in only} if only else set()
        # ATS boards are pure HTTPS (no browser). Run first when configured.
        ats_cfg = platforms.get("ats")
        if ats_cfg and ats_cfg.get("enabled", True) \
                and (not want or "ats" in want):
            try:
                from . import ats as ats_mod
                ats_jobs = ats_mod.collect_ats(self.cfg, run_id)
                ats_mod.enrich_ats(ats_jobs)
                jobs += ats_jobs
            except Exception as e:  # noqa: BLE001
                log.error("ats collection failed: %s", e)
        browser_names = [p for p in platform_order(self.cfg, only) if p != "ats"]
        if not browser_names:
            if self.cfg.email.alert_intake_enabled:
                jobs += self._collect_alerts()
            return jobs
        try:
            from .browser.session import attach_session
            from .browser import linkedin as li
            from .browser import naukri as nk
            session = attach_session(self.cfg.browser)
            collectors = {"linkedin": li.collect, "naukri": nk.collect}
            try:
                for name in browser_names:
                    if not platforms.get(name, {}).get("enabled", True):
                        continue
                    try:
                        jobs += collectors[name](session, queries, self.cfg, run_id)
                    except Exception as e:  # noqa: BLE001
                        log.error("%s collection failed: %s", name, e)
            finally:
                session.stop()
        except Exception as e:  # noqa: BLE001
            log.error("browser unavailable: %s", e)
        if self.cfg.email.alert_intake_enabled:
            jobs += self._collect_alerts()
        else:
            log.debug("alert-email intake disabled; web collection only")
        return jobs

    def _collect_alerts(self) -> list[Job]:
        try:
            from .mail.reader import MailReader
            from .mail import alerts
            reader = MailReader()
            if not reader.configured:
                return []
            from .config import get_secret as _get_secret
            folder = _get_secret("JOB_ALERTS_FOLDER") or "JobAlerts"
            out: list[Job] = []
            for raw in reader.fetch_alerts(folder=folder):
                out += alerts.parse_email(raw)
            log.info("alert-email intake: %d jobs", len(out))
            return out
        except Exception as e:  # noqa: BLE001
            log.error("alert intake failed: %s", e)
            return []

    # ---- run --------------------------------------------------------------
    def run(self, phase: str = "full", dry_run: bool = True,
            platforms: list[str] | None = None, force: bool = False) -> dict:
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        if force:
            release_run_lock()
        if not acquire_run_lock(run_id):
            log.error("another run is already in progress; refusing to double-run "
                      "(use --force to override)")
            return {"run_id": run_id, "refused": True,
                    "detail": "another run is already in progress"}
        try:
            return self._run_inner(run_id, phase, dry_run, platforms, force)
        finally:
            release_run_lock()

    def _run_inner(self, run_id: str, phase: str, dry_run: bool,
                   platforms: list[str] | None, force: bool = False) -> dict:
        self.store.start_run(run_id, phase)
        log.info("run %s phase=%s dry_run=%s platforms=%s", run_id, phase, dry_run,
                 platforms or "both")

        from .browser.pacing import in_quiet_hours
        if in_quiet_hours(self.cfg.apply) and not force:
            summary = {"run_id": run_id, "quiet_hours_skip": True,
                       "detail": "inside quiet hours; no collection, no apply, no email "
                                 "(re-run with --force for an attended overnight run)"}
            self.store.finish_run(run_id, summary)
            log.warning("run %s skipped: quiet hours %s-%s (use --force to run anyway)",
                        run_id,
                        self.cfg.apply.quiet_hours.get("start"),
                        self.cfg.apply.quiet_hours.get("end"))
            return summary
        if in_quiet_hours(self.cfg.apply) and force:
            log.warning("run %s: --force overrides quiet hours %s-%s; "
                        "attended run assumed", run_id,
                        self.cfg.apply.quiet_hours.get("start"),
                        self.cfg.apply.quiet_hours.get("end"))

        if not self.facts.data:
            log.error("candidate_facts.yaml missing/empty")
        queries = build_queries(self.cfg, self.resume)
        raw_jobs = self.collect(queries, run_id, only=platforms)

        counters = {
            "discovered": len(raw_jobs), "unique": 0, "discarded": 0,
            "inbox": 0, "auto_applied": 0, "apply_failed": 0,
            "would_apply_dryrun": 0, "llm_calls": 0, "deferred_cap": 0,
            "inbox_queued": 0, "applied_queued": 0,
        }
        inbox_items: list[tuple[Job, MatchResult]] = []
        applied_items: list[tuple[Job, MatchResult]] = []
        failed_items: list[tuple[Job, MatchResult]] = []
        gap_pool: list[tuple[Job, float]] = []
        # Cross-platform duplicates (same job on LinkedIn+Naukri) share a
        # dedup_key: process the first occurrence only, so counters stay
        # truthful and no job is scored twice in one run.
        seen_keys: set[str] = set()

        for job in raw_jobs:
            if job.dedup_key in seen_keys:
                counters["duplicates"] = counters.get("duplicates", 0) + 1
                continue
            seen_keys.add(job.dedup_key)
            block, why = is_blocklisted(job, self.cfg)
            if block:
                jid = self.store.upsert_job(job.to_db(), run_id)
                self.store.record_event(jid, "blocklisted", why, job.dedup_key, run_id)
                continue
            spam, why = is_obvious_spam(job)
            jid = self.store.upsert_job(job.to_db(), run_id)
            if spam:
                self.store.record_event(jid, "discarded", why, job.dedup_key, run_id)
                counters["discarded"] += 1
                continue
            if self.store.has_event(jid, "applied") or self.store.has_event(jid, "emailed"):
                continue  # idempotency (real actions only)
            if dry_run and self.store.has_event(jid, "dryrun"):
                continue  # dry-run idempotency; must not block a later live run
            counters["unique"] += 1
            # Scoring is silent otherwise; log progress so long runs never look stuck.
            if counters["unique"] % 10 == 0:
                log.info("run %s scored %d/%d (llm_calls=%d)", run_id,
                         counters["unique"], len(raw_jobs), counters["llm_calls"])

            try:
                res = match_job(job, jid, self.facts, self.cfg, self.resume,
                                llm=self.llm, use_llm=self.cfg.llm.enabled,
                                rerank=self.rerank)
            except PaidModelError as e:
                log.error("paid model refused: %s", e)
                res = match_job(job, jid, self.facts, self.cfg, self.resume, llm=None, use_llm=False)
            except Exception as e:  # noqa: BLE001 - one bad job must never kill a run
                from .logging_setup import scrub
                log.error("scoring failed for %s: %s", job.canonical_url, scrub(str(e)))
                counters["errors"] = counters.get("errors", 0) + 1
                self.store.record_event(jid, "error", f"scoring crashed: {e}",
                                        job.dedup_key, run_id)
                continue
            if res.llm_used:
                counters["llm_calls"] += 1

            bucket = res.decision.bucket
            from .gaps import RELEVANCE_FLOOR
            if res.overall_match >= RELEVANCE_FLOOR:
                gap_pool.append((job, res.overall_match))
            self.store.upsert_score(jid, run_id, {
                "overall_match": res.overall_match, "deterministic_score": res.deterministic_score,
                "llm_score": res.llm_score, "bucket": bucket, "reasons": res.reasons,
                "evidence": res.evidence, "missing_facts": res.decision.missing_facts,
                "resume_used": res.resume_used,
            })

            if bucket == BUCKET_DISCARD:
                counters["discarded"] += 1
                self.store.record_event(jid, "discarded", res.decision.reason, job.dedup_key, run_id)
                continue

            if bucket == BUCKET_APPLY and not dry_run and self.cfg.apply.live_submit_enabled:
                # Daily submit ceiling: pacing protection, enforced here. Deferred
                # jobs are NOT emailed and NOT marked applied, so the next day's
                # run retries them (the cap resets at UTC midnight).
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if (self.store.applied_today(job.source, today)
                        >= self.cfg.apply.daily_auto_apply_cap_per_platform):
                    counters["deferred_cap"] += 1
                    self.store.record_event(jid, "deferred_cap",
                                            "daily auto-apply cap reached; retried next run",
                                            job.dedup_key, run_id)
                    continue
                try:
                    ok, detail = self._apply(job, res, run_id)
                except Exception as e:  # noqa: BLE001 - e.g. browser died mid-run
                    from .logging_setup import scrub
                    log.error("apply crashed for %s: %s", job.canonical_url,
                              scrub(str(e)))
                    counters["errors"] = counters.get("errors", 0) + 1
                    ok, detail = False, f"apply crashed: {e}"
                if ok:
                    counters["auto_applied"] += 1
                    applied_items.append((job, res))
                    self.store.record_event(jid, "applied", detail, job.dedup_key, run_id)
                else:
                    counters["apply_failed"] += 1
                    failed_items.append((job, res))
                    self.store.record_event(jid, "inbox", f"apply failed: {detail}", job.dedup_key, run_id)
                    counters["inbox"] += 1
                    # NOTE: the "emailed" event is recorded only after the digest
                    # below is actually sent, so a failed send retries next run.
            elif bucket == BUCKET_APPLY and (dry_run or not self.cfg.apply.live_submit_enabled):
                counters["would_apply_dryrun"] += 1
                applied_items.append((job, res))
                self.store.record_application(jid, "would_apply_dryrun", run_id,
                                              job.source, res.decision.reason)
                # NOTE: the "dryrun" event is recorded only for items actually
                # shown in a delivered digest (below), so overflow/failed sends
                # are retried instead of vanishing.
            else:  # BUCKET_INBOX
                counters["inbox"] += 1
                inbox_items.append((job, res))
                self.store.record_event(jid, "inbox", res.decision.reason, job.dedup_key, run_id)

        # email
        if self.cfg.email.digest_enabled and (inbox_items or applied_items or failed_items
                                              or self.cfg.email.send_daily_summary_even_if_zero):
            from .gaps import skill_gaps
            gaps = skill_gaps(gap_pool, self.resume, top_n=10)
            counters["skill_gaps"] = len(gaps)
            self.send_digest(run_id, inbox_items, applied_items, failed_items,
                             gaps, counters,
                             dry_run=dry_run or not self.cfg.apply.live_submit_enabled)

        self.store.finish_run(run_id, counters)
        log.info("run %s complete: %s", run_id, counters)
        return {"run_id": run_id, **counters}

    def send_digest(self, run_id: str, inbox_items, applied_items, failed_items,
                    gaps, counters: dict, dry_run: bool) -> bool:
        """Prioritize, build, send, and record delivery events. Returns sent.

        Shared by live runs and `resend`: only a confirmed send earns the
        emailed/dryrun events, so failed sends always retry instead of vanishing.
        """
        max_packets = self.cfg.email.max_packet_emails_per_run
        inbox_items, inbox_queued = prioritize(inbox_items, max_packets)
        applied_items, applied_queued = prioritize(applied_items, max_packets)
        counters["inbox_queued"] = inbox_queued
        counters["applied_queued"] = applied_queued
        html, text = build_digest(run_id, inbox_items, applied_items, failed_items,
                                  counters, dry_run=dry_run, gaps=gaps)
        subject = (f"[JobAgent] {counters.get('inbox', 0)} inbox, "
                   f"{counters.get('would_apply_dryrun', 0) or counters.get('auto_applied', 0)} applied")
        sent = self.mailer.send(subject, html, text)
        counters["email_sent"] = int(sent)
        if sent:
            for job, _ in inbox_items + failed_items:
                jid = self.store.upsert_job(job.to_db(), run_id)
                self.store.record_event(jid, "emailed", "digest", job.dedup_key, run_id)
            if dry_run:
                for job, _ in applied_items:
                    jid = self.store.upsert_job(job.to_db(), run_id)
                    self.store.record_event(jid, "dryrun", "digest", job.dedup_key, run_id)
        return sent

    def resend_run(self, run_id: str | None = None) -> dict:
        """Rebuild and send a past run's digest from stored scores. No browser,
        no model calls — seconds, not an hour. Marks delivery like a live send."""
        import json
        from .clean import RouteDecision
        from .gaps import RELEVANCE_FLOOR, skill_gaps
        if run_id is None:
            with self.store._conn() as c:
                row = c.execute("SELECT run_id, summary FROM runs "
                                "ORDER BY started_at DESC LIMIT 1").fetchone()
                if not row:
                    return {"sent": False, "detail": "no runs yet"}
                run_id, summary_raw = row["run_id"], row["summary"]
        else:
            with self.store._conn() as c:
                row = c.execute("SELECT summary FROM runs WHERE run_id = ?",
                                (run_id,)).fetchone()
                summary_raw = row["summary"] if row else "{}"
        try:
            counters = json.loads(summary_raw or "{}")
        except json.JSONDecodeError:
            counters = {}

        def to_result(job: Job, s) -> MatchResult:
            reasons = json.loads(s["reasons"] or "[]")
            evidence = json.loads(s["evidence"] or "[]")
            missing = json.loads(s["missing_facts"] or "[]")
            return MatchResult(
                job_id=s["job_id"], overall_match=s["overall_match"],
                deterministic_score=s["deterministic_score"],
                llm_score=s["llm_score"],
                decision=RouteDecision(s["bucket"], f"restored from run {run_id}",
                                       missing),
                reasons=reasons, evidence=evidence,
                resume_used=s["resume_used"] or "default",
                llm_used=s["llm_score"] is not None)

        inbox_items, applied_items, failed_items = [], [], []
        gap_pool = []
        with self.store._conn() as c:
            for s in c.execute("SELECT * FROM scores WHERE run_id = ?", (run_id,)):
                job = job_from_row(self.store.get_job(s["job_id"]))
                res = to_result(job, s)
                if s["overall_match"] is not None and s["overall_match"] >= RELEVANCE_FLOOR:
                    gap_pool.append((job, s["overall_match"]))
                if s["bucket"] == BUCKET_INBOX:
                    inbox_items.append((job, res))
            for a in c.execute("SELECT * FROM applications WHERE run_id = ?", (run_id,)):
                job = job_from_row(self.store.get_job(a["job_id"]))
                s = self.store.get_score(a["job_id"], run_id)
                if s is None:
                    continue
                res = to_result(job, s)
                if a["status"] == "applied":
                    applied_items.append((job, res))
                elif a["status"] == "apply_failed":
                    failed_items.append((job, res))
                elif a["status"] == "would_apply_dryrun":
                    applied_items.append((job, res))
        live = self._run_had_live_applies(run_id)
        gaps = skill_gaps(gap_pool, self.resume, top_n=10)
        counters["skill_gaps"] = len(gaps)
        sent = self.send_digest(run_id, inbox_items, applied_items, failed_items,
                                gaps, counters, dry_run=not live)
        log.info("resend %s -> sent=%s", run_id, sent)
        return {"run_id": run_id, "sent": sent, **counters}

    def _run_had_live_applies(self, run_id: str) -> bool:
        with self.store._conn() as c:
            row = c.execute("SELECT 1 FROM applications WHERE run_id = ? AND status = 'applied'",
                            (run_id,)).fetchone()
            return row is not None

    def _apply(self, job: Job, res: MatchResult, run_id: str) -> tuple[bool, str]:
        from .browser.session import attach_session, CheckpointError
        from .browser import linkedin as li
        from .browser import naukri as nk
        resume_path = _resume_paths(self.facts)[0] if _resume_paths(self.facts) else ""
        session = attach_session(self.cfg.browser)
        try:
            if job.source == "linkedin" and job.apply_type == "easy_apply":
                ok, detail = li.easy_apply(session, job, self.facts, self.cfg, resume_path, self.autofill)
            elif job.source == "naukri" and job.apply_type == "naukri_apply":
                ok, detail = nk.in_platform_apply(session, job, self.facts, self.cfg, resume_path, self.autofill)
            else:
                return False, f"not in-platform ({job.apply_type})"
            self.store.record_application(res.job_id, "applied" if ok else "apply_failed",
                                          run_id, job.source, detail, res.resume_used)
            return ok, detail
        except CheckpointError:
            return False, "checkpoint"
        finally:
            session.stop()