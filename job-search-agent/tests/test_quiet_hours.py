from jobagent.browser.pacing import in_quiet_hours
from jobagent.config import ApplyConfig


def test_quiet_hours_overnight_window():
    cfg = ApplyConfig(quiet_hours={"start": "22:30", "end": "08:00"})
    from datetime import datetime
    assert in_quiet_hours(cfg, datetime(2026, 1, 1, 23, 0))
    assert in_quiet_hours(cfg, datetime(2026, 1, 1, 7, 59))
    assert not in_quiet_hours(cfg, datetime(2026, 1, 1, 9, 15))
    assert not in_quiet_hours(cfg, datetime(2026, 1, 1, 22, 29))


def test_quiet_hours_unpadded_hour():
    # Regression: "7:00" must behave like "07:00", not wrap past midnight.
    cfg = ApplyConfig(quiet_hours={"start": "7:00", "end": "08:00"})
    from datetime import datetime
    assert not in_quiet_hours(cfg, datetime(2026, 1, 1, 0, 59))
    assert in_quiet_hours(cfg, datetime(2026, 1, 1, 7, 30))
    assert not in_quiet_hours(cfg, datetime(2026, 1, 1, 9, 0))


def test_quiet_hours_bad_value_falls_back():
    cfg = ApplyConfig(quiet_hours={"start": "nonsense", "end": "08:00"})
    from datetime import datetime
    # falls back to 22:30-08:00
    assert in_quiet_hours(cfg, datetime(2026, 1, 1, 23, 0))
    assert not in_quiet_hours(cfg, datetime(2026, 1, 1, 12, 0))


def test_run_skips_inside_quiet_hours(monkeypatch, cfg, facts, tmp_path):
    import jobagent.pipeline as pl
    from jobagent.resume import ResumeProfile

    monkeypatch.setattr(pl, "load_facts", lambda *a, **k: facts)
    monkeypatch.setattr(pl, "load_or_build", lambda paths: ResumeProfile(skills=["python"]))
    monkeypatch.setattr(pl.Mailer, "send", lambda self, s, h, t="": True)

    p = pl.Pipeline(cfg)
    p.cfg.apply.quiet_hours = {"start": "00:00", "end": "23:59"}  # always quiet

    def boom(queries, run_id):
        raise AssertionError("collect must not run in quiet hours")

    monkeypatch.setattr(p, "collect", boom)
    result = p.run(dry_run=True)
    assert result.get("quiet_hours_skip") is True