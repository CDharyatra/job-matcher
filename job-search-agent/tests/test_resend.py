from jobagent.models import Job
from jobagent.resume import ResumeProfile


def seed_run(store):
    mk = lambda i, bucket, score, status=None: (i, bucket, score, status)
    jobs = {}
    for i, bucket, score, status in [
        mk(1, "B_inbox", 86.0, None),
        mk(2, "A_autoapply", 81.0, "would_apply_dryrun"),
        mk(3, "C_discard", 40.0, None),
    ]:
        job = Job(source="linkedin", title=f"Job {i}", company="C",
                  location="Bengaluru", canonical_url=f"https://x/r{i}",
                  description_text="Python backend role. " * 20,
                  apply_type="easy_apply")
        jid = store.upsert_job(job.to_db(), "rx")
        jobs[i] = jid
        store.upsert_score(jid, "rx", {"overall_match": score,
                                       "deterministic_score": score,
                                       "llm_score": None, "bucket": bucket,
                                       "reasons": ["r"], "evidence": [],
                                       "missing_facts": [], "resume_used": "d"})
        if status:
            store.record_application(jid, status, "rx", "linkedin", "d")
    store.start_run("rx", "full")
    return jobs


def make_pipeline(monkeypatch, cfg, facts, store):
    import jobagent.pipeline as pl
    from jobagent.resume import ResumeProfile as RP

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    monkeypatch.setattr(pl, "load_or_build", lambda paths: RP(skills=["python"]))
    return pl.Pipeline(cfg, store)


def test_resend_sends_and_marks(monkeypatch, cfg, facts, store):
    import jobagent.pipeline as pl
    p = make_pipeline(monkeypatch, cfg, facts, store)
    monkeypatch.setattr(pl.Mailer, "send", lambda self, s, h, t="": True)
    seed_run(store)
    result = p.resend_run("rx")
    assert result["sent"] is True
    with store._conn() as c:
        emailed = c.execute("SELECT COUNT(*) n FROM ledger WHERE event='emailed'").fetchone()["n"]
        dryrun = c.execute("SELECT COUNT(*) n FROM ledger WHERE event='dryrun'").fetchone()["n"]
    assert emailed == 1  # only the inbox job
    assert dryrun == 1  # only the would-apply job (discard untouched)


def test_resend_failed_send_marks_nothing(monkeypatch, cfg, facts, store):
    import jobagent.pipeline as pl
    p = make_pipeline(monkeypatch, cfg, facts, store)
    monkeypatch.setattr(pl.Mailer, "send", lambda self, s, h, t="": False)
    seed_run(store)
    result = p.resend_run("rx")
    assert result["sent"] is False
    with store._conn() as c:
        n = c.execute("SELECT COUNT(*) n FROM ledger WHERE event IN ('emailed','dryrun')").fetchone()["n"]
    assert n == 0


def test_resend_unknown_run(monkeypatch, cfg, facts, store):
    import jobagent.pipeline as pl
    p = make_pipeline(monkeypatch, cfg, facts, store)
    monkeypatch.setattr(pl.Mailer, "send", lambda self, s, h, t="": True)
    result = p.resend_run("nope")
    assert result["sent"] is True  # empty digest still sends (summary mail)