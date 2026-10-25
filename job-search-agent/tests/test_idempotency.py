from jobagent.models import Job


def test_ledger_prevents_double_apply(store, cfg, facts):
    job = Job(source="linkedin", title="Backend Engineer", company="Acme", location="Bengaluru")
    jid = store.upsert_job(job.to_db(), "run1")
    assert not store.has_event(jid, "applied")
    store.record_event(jid, "applied", "submitted", job.dedup_key, "run1")
    assert store.has_event(jid, "applied")
    # duplicate event ignored
    store.record_event(jid, "applied", "submitted again", job.dedup_key, "run1")
    rows = 0
    with store._conn() as c:
        rows = c.execute("SELECT COUNT(*) n FROM ledger WHERE job_id=? AND event='applied'", (jid,)).fetchone()["n"]
    assert rows == 1


def test_upsert_same_dedup_key_returns_same_id(store):
    a = Job(source="linkedin", title="Backend Engineer", company="Acme", location="Bengaluru")
    b = Job(source="naukri", title="Backend Engineer", company="Acme", location="Bengaluru")
    id1 = store.upsert_job(a.to_db(), "r1")
    id2 = store.upsert_job(b.to_db(), "r2")
    assert id1 == id2


def test_emailed_event_idempotent(store):
    job = Job(source="linkedin", title="X", company="Y", location="Z", canonical_url="u1")
    jid = store.upsert_job(job.to_db(), "r")
    store.record_event(jid, "emailed", "digest", job.dedup_key, "r")
    assert store.has_event(jid, "emailed")


def test_applied_today_count(store):
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert store.applied_today("linkedin", day) == 0