import argparse

from jobagent.clean import BUCKET_APPLY, BUCKET_DISCARD, RouteDecision
from jobagent.matcher import MatchResult
from jobagent.models import Job
from jobagent.resume import ResumeProfile


def ns(job, live=False):
    return argparse.Namespace(job=job, live=live)


def seed_job(store):
    job = Job(source="naukri", title="ML Engineer", company="Acme",
              location="Bengaluru", canonical_url="https://u/apply-1",
              description_text="Python ML role. " * 20, apply_type="naukri_apply")
    return store.upsert_job(job.to_db(), "seed")


def fake_pipeline(monkeypatch, cfg, facts, store):
    import jobagent.pipeline as pl

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    monkeypatch.setattr(pl, "load_or_build",
                        lambda paths: ResumeProfile(skills=["python"]))
    p = pl.Pipeline(cfg, store)
    monkeypatch.setattr(pl, "Pipeline", lambda *a, **k: p)
    return p


class FakeSession:
    def stop(self):
        pass


def fake_browser(monkeypatch):
    import jobagent.browser.session as sess
    import jobagent.browser.naukri as nk
    import jobagent.browser.linkedin as li
    monkeypatch.setattr(sess, "attach_session", lambda cfg: FakeSession())
    monkeypatch.setattr(nk, "enrich_from_detail", lambda s, j, c: j)
    monkeypatch.setattr(li, "enrich_from_detail", lambda s, j, c: j)


def fake_match(monkeypatch, bucket, score=80.0):
    import jobagent.matcher as mt

    def go(job, job_id, facts, cfg, profile, llm=None, use_llm=True, rerank=None):
        return MatchResult(job_id=job_id, overall_match=score,
                           deterministic_score=score, llm_score=None,
                           decision=RouteDecision(bucket, "test", []),
                           reasons=[], evidence=[], resume_used="d")
    monkeypatch.setattr(mt, "match_job", go)


def test_unknown_job(monkeypatch, cfg, facts, store):
    import jobagent.cli as cli
    fake_pipeline(monkeypatch, cfg, facts, store)
    assert cli.cmd_apply(ns(99999)) == 2


def test_already_applied_refused(monkeypatch, cfg, facts, store):
    import jobagent.cli as cli
    fake_pipeline(monkeypatch, cfg, facts, store)
    jid = seed_job(store)
    store.record_event(jid, "applied", "earlier", "k", "r0")
    assert cli.cmd_apply(ns(jid, live=True)) == 2


def test_dry_run_verdict_no_submit(monkeypatch, cfg, facts, store):
    import jobagent.cli as cli
    import jobagent.pipeline as pl
    p = fake_pipeline(monkeypatch, cfg, facts, store)
    fake_browser(monkeypatch)
    fake_match(monkeypatch, BUCKET_APPLY)
    jid = seed_job(store)
    monkeypatch.setattr(p, "_apply", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not submit in dry run")))
    assert cli.cmd_apply(ns(jid)) == 0
    assert not store.has_event(jid, "applied")


def test_discard_bucket_refused(monkeypatch, cfg, facts, store):
    import jobagent.cli as cli
    fake_pipeline(monkeypatch, cfg, facts, store)
    fake_browser(monkeypatch)
    fake_match(monkeypatch, BUCKET_DISCARD, score=40.0)
    jid = seed_job(store)
    assert cli.cmd_apply(ns(jid)) == 0
    assert not store.has_event(jid, "applied")


def test_only_one_browser_session_at_a_time(monkeypatch, cfg, facts, store):
    # Regression: two live Playwright sync sessions in one process crash with
    # "Sync API inside the asyncio loop". The enrich session must be stopped
    # before _apply attaches its own.
    import jobagent.cli as cli
    cfg.apply.live_submit_enabled = True
    cfg.apply.daily_auto_apply_cap_per_platform = 5
    p = fake_pipeline(monkeypatch, cfg, facts, store)
    fake_browser(monkeypatch)
    fake_match(monkeypatch, BUCKET_APPLY)
    events = []

    class TrackedSession(FakeSession):
        def stop(self):
            events.append("enrich-stopped")

    import jobagent.browser.session as sess
    monkeypatch.setattr(sess, "attach_session", lambda cfg: TrackedSession())

    def fake_apply(job, res, run_id):
        events.append("apply-ran")
        assert "enrich-stopped" in events, "enrich session still open during _apply"
        return True, "ok"

    monkeypatch.setattr(p, "_apply", fake_apply)
    assert cli.cmd_apply(ns(seed_job(store), live=True)) == 0
    assert events == ["enrich-stopped", "apply-ran"]


def test_live_submit_records(monkeypatch, cfg, facts, store):
    import jobagent.cli as cli
    cfg.apply.live_submit_enabled = True
    cfg.apply.daily_auto_apply_cap_per_platform = 5
    p = fake_pipeline(monkeypatch, cfg, facts, store)
    fake_browser(monkeypatch)
    fake_match(monkeypatch, BUCKET_APPLY)
    called = []
    monkeypatch.setattr(p, "_apply",
                        lambda job, res, run_id: (called.append(job), (True, "ok"))[1])
    jid = seed_job(store)
    assert cli.cmd_apply(ns(jid, live=True)) == 0
    assert len(called) == 1  # exactly one submit attempt, then real code records it


def test_live_refused_when_flag_off(monkeypatch, cfg, facts, store):
    import jobagent.cli as cli
    cfg.apply.live_submit_enabled = False
    fake_pipeline(monkeypatch, cfg, facts, store)
    fake_browser(monkeypatch)
    fake_match(monkeypatch, BUCKET_APPLY)
    assert cli.cmd_apply(ns(seed_job(store), live=True)) == 2


def test_live_refused_at_cap(monkeypatch, cfg, facts, store):
    import jobagent.cli as cli
    cfg.apply.live_submit_enabled = True
    cfg.apply.daily_auto_apply_cap_per_platform = 0
    fake_pipeline(monkeypatch, cfg, facts, store)
    fake_browser(monkeypatch)
    fake_match(monkeypatch, BUCKET_APPLY)
    assert cli.cmd_apply(ns(seed_job(store), live=True)) == 2