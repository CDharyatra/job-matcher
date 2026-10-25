from jobagent.golden import build_golden_entries, write_golden_set
from jobagent.models import Job


def seed(store, n=10):
    for i in range(n):
        job = Job(source="linkedin", title=f"Job {i}", company="C",
                  location="Bengaluru", canonical_url=f"https://x/{i}",
                  description_text="Python stuff. " * 20, apply_type="easy_apply")
        jid = store.upsert_job(job.to_db(), "r1")
        store.upsert_score(jid, "r1", {"overall_match": float(95 - i * 5),
                                       "deterministic_score": 80.0, "llm_score": None,
                                       "bucket": "B", "reasons": [], "evidence": [],
                                       "missing_facts": [], "resume_used": "d"})


def test_stratified_entries(store):
    seed(store, 10)
    entries = build_golden_entries(store, n=10)
    assert len(entries) == 10
    assert all(e["label"] == "" for e in entries)
    scores = [e["system_score"] for e in entries]
    assert scores[0] == 95.0  # top band first
    assert scores[-1] == 50.0  # bottom band last
    assert entries[0]["url"] == "https://x/0"
    assert "Python stuff" in entries[0]["description"]


def test_fewer_jobs_than_requested(store):
    seed(store, 3)
    assert len(build_golden_entries(store, n=50)) == 3


def test_empty_store(store):
    assert build_golden_entries(store, n=50) == []


def test_append_preserves_labels_and_dedupes(tmp_path, store):
    from jobagent.golden import append_golden_set
    seed(store, 6)
    entries = build_golden_entries(store, n=6)
    path = tmp_path / "golden_set.yaml"
    write_golden_set(path, entries[:4], overwrite=True)
    import yaml
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows[0]["label"] = "apply"
    rows[1]["label"] = "discard"
    path.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    _, added = append_golden_set(path, entries, 10)
    final = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert added == 2  # 6 total minus 4 already present
    assert len(final) == 6
    assert final[0]["label"] == "apply"  # labels intact
    assert final[1]["label"] == "discard"
    assert all(e["label"] == "" for e in final[4:])


def test_write_roundtrip_and_overwrite_guard(tmp_path, store):
    seed(store, 5)
    entries = build_golden_entries(store, n=5)
    path = tmp_path / "golden_set.yaml"
    out = write_golden_set(path, entries)
    assert out == path
    import pytest
    with pytest.raises(FileExistsError):
        write_golden_set(path, entries)
    out2 = write_golden_set(path, entries, overwrite=True)
    assert out2 == path
    import yaml
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(rows) == 5 and rows[0]["title"] == "Job 0"