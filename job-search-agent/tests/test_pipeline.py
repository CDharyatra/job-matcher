import json

from jobagent.llm.adapter import LLMResult
from jobagent.models import Job
from jobagent.pipeline import Pipeline
from jobagent.resume import ResumeProfile


class FakeLLM:
    def complete_json(self, prompt, chain=None, allow_pii=False):
        return LLMResult(ok=False, error="down")  # force deterministic-only


class FakeStore:
    pass


def make_pipeline(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    monkeypatch.setattr(pl, "load_or_build", lambda paths: ResumeProfile(
        skills=["python", "postgresql", "aws"], titles=["Senior Backend Engineer"]))
    monkeypatch.setattr(pl.Mailer, "send", lambda self, s, h, t="": False)  # no real mail
    # Quiet hours are covered by test_quiet_hours.py; pipeline tests must run
    # deterministically at any hour of day.
    monkeypatch.setattr("jobagent.browser.pacing.in_quiet_hours",
                        lambda cfg, now=None: False)
    # Tests must never touch the real run lock.
    monkeypatch.setattr(pl, "_lock_path", lambda: tmp_path / ".run.lock")

    p = Pipeline(cfg)
    p.llm = FakeLLM()
    p.evaluate = None
    jobs = [
        Job(source="linkedin", title="Senior Backend Engineer", company="Good",
            location="Bengaluru", apply_type="easy_apply", canonical_url="https://a",
            description_text="Python PostgreSQL AWS 4-8 years", experience_min=4,
            experience_max=8, posted_at="2026-09-28T08:00:00+00:00"),
        Job(source="linkedin", title="WordPress Intern", company="X", location="Bengaluru",
            apply_type="easy_apply", canonical_url="https://b",
            description_text="wordpress intern", posted_at="2026-09-28T08:00:00+00:00"),
        Job(source="naukri", title="Senior Backend Engineer", company="Ext",
            location="Bengaluru", apply_type="external_ats", canonical_url="https://c",
            description_text="Python PostgreSQL AWS 4-8 years", experience_min=4,
            experience_max=8, posted_at="2026-09-28T08:00:00+00:00"),
    ]
    monkeypatch.setattr(p, "collect", lambda queries, run_id, only=None: jobs)
    return p


def test_dry_run_never_submits(monkeypatch, cfg, facts, tmp_path):
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    result = p.run(dry_run=True)
    assert result["auto_applied"] == 0
    assert result["would_apply_dryrun"] >= 1
    assert result["discarded"] >= 1


def test_run_is_idempotent(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    monkeypatch.setattr(pl.Mailer, "send", lambda self, s, h, t="": True)
    r1 = p.run(dry_run=True)
    r2 = p.run(dry_run=True)
    # delivered digests mark jobs, so the second run reports nothing new
    assert r2["would_apply_dryrun"] == 0
    assert r2["inbox"] == 0


def test_failed_send_retries_next_run(monkeypatch, cfg, facts, tmp_path):
    # send is mocked False in make_pipeline: nothing delivered, nothing marked
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    r1 = p.run(dry_run=True)
    r2 = p.run(dry_run=True)
    assert r1["would_apply_dryrun"] >= 1
    assert r2["would_apply_dryrun"] >= 1  # retried, not silently dropped


def test_run_lock_refuses_double_run(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl
    from jobagent.resume import ResumeProfile

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    monkeypatch.setattr(pl, "load_or_build", lambda paths: ResumeProfile(skills=["python"]))
    monkeypatch.setattr(pl, "acquire_run_lock", lambda run_id: True)
    released = []
    monkeypatch.setattr(pl, "release_run_lock", lambda: released.append(True))
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    result = p.run(dry_run=True)
    assert released  # lock released even on success
    assert "refused" not in result


def test_run_lock_blocks_second_runner(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl
    from jobagent.resume import ResumeProfile

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    monkeypatch.setattr(pl, "load_or_build", lambda paths: ResumeProfile(skills=["python"]))
    monkeypatch.setattr(pl, "acquire_run_lock", lambda run_id: False)
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    result = p.run(dry_run=True)
    assert result.get("refused") is True


def test_acquire_lock_atomic_and_stale(tmp_path, monkeypatch):
    import time
    import jobagent.pipeline as pl

    monkeypatch.setattr(pl, "_lock_path", lambda: tmp_path / ".run.lock")
    assert pl.acquire_run_lock("r1") is True
    assert pl.acquire_run_lock("r2") is False  # held
    pl.release_run_lock()
    assert pl.acquire_run_lock("r3") is True
    pl.release_run_lock()
    # stale lock (old mtime) is replaced
    (tmp_path / ".run.lock").write_text("{}", encoding="utf-8")
    old = time.time() - 7 * 3600
    import os
    os.utime(tmp_path / ".run.lock", (old, old))
    assert pl.acquire_run_lock("r4") is True
    pl.release_run_lock()


def test_force_bypasses_quiet_hours(monkeypatch, cfg, facts, tmp_path):
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    monkeypatch.setattr("jobagent.browser.pacing.in_quiet_hours",
                        lambda cfg, now=None: True)
    skipped = p.run(dry_run=True)
    assert skipped.get("quiet_hours_skip") is True
    ran = p.run(dry_run=True, force=True)
    assert "quiet_hours_skip" not in ran
    assert ran["would_apply_dryrun"] >= 1


def test_cross_platform_dupes_processed_once(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl
    from jobagent.models import Job

    monkeypatch.setattr("jobagent.browser.pacing.in_quiet_hours",
                        lambda cfg, now=None: False)

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    from jobagent.resume import ResumeProfile
    monkeypatch.setattr(pl, "load_or_build", lambda paths: ResumeProfile(skills=["python"]))
    monkeypatch.setattr(pl.Mailer, "send", lambda self, s, h, t="": True)
    p = pl.Pipeline(cfg)
    base = dict(source="linkedin", title="Backend Engineer", company="Acme",
                location="Bengaluru", apply_type="easy_apply", canonical_url="https://a",
                description_text="Python backend role. " * 20,
                posted_at="2026-09-28T08:00:00+00:00")
    dupe = dict(base)
    dupe.update(source="naukri", canonical_url="https://b")
    monkeypatch.setattr(p, "collect",
                        lambda queries, run_id, only=None: [Job(**base), Job(**dupe)])
    result = p.run(dry_run=True)
    assert result.get("duplicates", 0) == 1
    assert result["unique"] == 1


def test_scoring_crash_does_not_kill_run(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("judge exploded")

    monkeypatch.setattr(pl, "match_job", boom)
    result = p.run(dry_run=True)
    assert result.get("errors", 0) >= 1
    assert "run_id" in result  # completed, with summary + (no) email attempt


def test_apply_session_death_goes_to_inbox(monkeypatch, cfg, facts, tmp_path):
    import jobagent.browser.session as sess

    cfg.apply.live_submit_enabled = True
    cfg.apply.daily_auto_apply_cap_per_platform = 5
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)

    def dead(_cfg):
        raise sess.SessionDeadError("wedged")

    monkeypatch.setattr(sess, "attach_session", dead)
    monkeypatch.setattr(sess, "relaunch_dedicated_browser", lambda cfg: False)
    monkeypatch.setattr(p, "_apply",
                        lambda job, res, run_id: (_ for _ in ()).throw(
                            sess.SessionDeadError("wedged")))
    result = p.run(dry_run=False)
    assert result["apply_failed"] >= 1
    assert result["inbox"] >= 1


def test_attach_session_relaunches_once(monkeypatch):
    import jobagent.browser.session as sess

    calls = {"starts": 0}

    class FakeSession:
        def __init__(self, cfg):
            pass

        def start(self):
            calls["starts"] += 1
            if calls["starts"] == 1:
                raise sess.SessionDeadError("wedged")
            return "SESSION"

    monkeypatch.setattr(sess, "BrowserSession", FakeSession)
    monkeypatch.setattr(sess, "relaunch_dedicated_browser", lambda cfg: True)
    assert sess.attach_session(object()) == "SESSION"
    assert calls["starts"] == 2


def test_attach_session_gives_up(monkeypatch):
    import jobagent.browser.session as sess

    class FakeSession:
        def __init__(self, cfg):
            pass

        def start(self):
            raise sess.SessionDeadError("dead")

    monkeypatch.setattr(sess, "BrowserSession", FakeSession)
    monkeypatch.setattr(sess, "relaunch_dedicated_browser", lambda cfg: False)
    import pytest
    with pytest.raises(sess.SessionDeadError):
        sess.attach_session(object())


def test_pids_on_port_parsing(monkeypatch):
    import jobagent.browser.session as sess
    import subprocess

    class Out:
        stdout = ("  TCP    127.0.0.1:9222         0.0.0.0:0  LISTENING       1234\n"
                  "  TCP    127.0.0.1:8080         0.0.0.0:0  LISTENING       9999\n")

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Out())
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    assert sess._pids_on_port(9222) == [1234]


def test_platform_order_config_first(monkeypatch, cfg):
    from jobagent.pipeline import platform_order
    cfg.platforms = {"order": ["naukri", "linkedin"]}
    assert platform_order(cfg, None) == ["naukri", "linkedin"]
    assert platform_order(cfg, ["linkedin"]) == ["linkedin"]
    cfg.platforms = {}
    assert platform_order(cfg, None) == ["linkedin", "naukri"]
    cfg.platforms = {"order": ["naukri", "bogus"]}
    assert platform_order(cfg, None) == ["naukri"]


def test_collect_respects_order(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl
    from jobagent.resume import ResumeProfile

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    monkeypatch.setattr(pl, "load_or_build", lambda paths: ResumeProfile(skills=["python"]))
    calls = []
    monkeypatch.setattr("jobagent.browser.linkedin.collect",
                        lambda *a, **k: calls.append("linkedin") or [])
    monkeypatch.setattr("jobagent.browser.naukri.collect",
                        lambda *a, **k: calls.append("naukri") or [])

    class FakeSession:
        def start(self): return self
        def stop(self): pass

    monkeypatch.setattr("jobagent.browser.session.BrowserSession",
                        lambda *a, **k: FakeSession())
    cfg.platforms = {"order": ["naukri", "linkedin"],
                     "naukri": {"enabled": True}, "linkedin": {"enabled": True}}
    p = pl.Pipeline(cfg)
    assert p.collect([], "r1") == []
    assert calls == ["naukri", "linkedin"]


def test_external_goes_to_inbox(monkeypatch, cfg, facts, tmp_path):
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    result = p.run(dry_run=True)
    assert result["inbox"] >= 1


def test_apply_cap_zero_defers_everything(monkeypatch, cfg, facts, tmp_path):
    cfg.apply.live_submit_enabled = True
    cfg.apply.daily_auto_apply_cap_per_platform = 0
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)

    def boom(job, res, run_id):
        raise AssertionError("_apply must not run when the cap is 0")

    monkeypatch.setattr(p, "_apply", boom)
    result = p.run(dry_run=False)
    assert result["auto_applied"] == 0
    assert result["would_apply_dryrun"] == 0
    assert result["deferred_cap"] >= 1


def test_apply_cap_allows_up_to_cap(monkeypatch, cfg, facts, tmp_path):
    cfg.apply.live_submit_enabled = True
    cfg.apply.daily_auto_apply_cap_per_platform = 5
    p = make_pipeline(monkeypatch, cfg, facts, tmp_path)
    monkeypatch.setattr(p, "_apply", lambda job, res, run_id: (True, "ok"))
    result = p.run(dry_run=False)
    assert result["auto_applied"] == 1
    assert result["deferred_cap"] == 0