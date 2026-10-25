from jobagent.clean import BUCKET_APPLY, BUCKET_DISCARD, BUCKET_INBOX, route
from jobagent.models import Job


def make_job(apply_type="easy_apply"):
    return Job(source="linkedin", title="Backend Engineer", company="X",
               location="Bengaluru", apply_type=apply_type)


def test_65_discard(cfg, facts):
    d = route(make_job(), 65, facts, cfg)
    assert d.bucket == BUCKET_DISCARD


def test_92_inbox_even_easy_apply(cfg, facts):
    d = route(make_job("easy_apply"), 92, facts, cfg)
    assert d.bucket == BUCKET_INBOX


def test_81_easy_apply_is_apply(cfg, facts):
    d = route(make_job("easy_apply"), 81, facts, cfg)
    assert d.bucket == BUCKET_APPLY


def test_81_external_is_inbox(cfg, facts):
    d = route(make_job("external_ats"), 81, facts, cfg)
    assert d.bucket == BUCKET_INBOX


def test_70_and_90_boundaries_inclusive(cfg, facts):
    assert route(make_job("easy_apply"), 70, facts, cfg).bucket == BUCKET_APPLY
    assert route(make_job("easy_apply"), 90, facts, cfg).bucket == BUCKET_APPLY
    assert route(make_job("easy_apply"), 90.1, facts, cfg).bucket == BUCKET_INBOX
    assert route(make_job("easy_apply"), 69.9, facts, cfg).bucket == BUCKET_DISCARD


def test_naukri_apply_is_apply(cfg, facts):
    assert route(make_job("naukri_apply"), 80, facts, cfg).bucket == BUCKET_APPLY


def _loc_job(location, apply_type="easy_apply"):
    return Job(source="linkedin", title="Backend Engineer", company="X",
               location=location, apply_type=apply_type)


def test_outside_bangalore_discards(cfg, facts):
    d = route(_loc_job("Hyderabad"), 85, facts, cfg)
    assert d.bucket == BUCKET_DISCARD
    assert "Bangalore" in d.reason


def test_outside_bangalore_discards_even_high_score(cfg, facts):
    assert route(_loc_job("Hyderabad"), 95, facts, cfg).bucket == BUCKET_DISCARD


def test_remote_stays_in_scope(cfg, facts):
    assert route(_loc_job("Remote"), 95, facts, cfg).bucket == BUCKET_INBOX
    assert route(_loc_job("Remote"), 81, facts, cfg).bucket == BUCKET_APPLY


def test_multi_city_with_bangalore_stays(cfg, facts):
    d = route(_loc_job("Bengaluru, Hyderabad, Delhi NCR"), 81, facts, cfg)
    assert d.bucket == BUCKET_APPLY


def test_blank_location_allowed(cfg, facts):
    assert route(_loc_job(""), 81, facts, cfg).bucket == BUCKET_APPLY


def _pay_job(smin, smax, cur="INR"):
    return Job(source="naukri", title="ML Engineer", company="X",
               location="Bengaluru", apply_type="naukri_apply",
               salary_min=smin, salary_max=smax, salary_currency=cur)


def test_pay_below_bar_discards(cfg, facts):
    cfg.routing.min_pay_lpa = 19.0
    d = route(_pay_job(800000, 1400000), 85, facts, cfg)
    assert d.bucket == BUCKET_DISCARD
    assert "pay" in d.reason


def test_pay_undisclosed_passes(cfg, facts):
    cfg.routing.min_pay_lpa = 19.0
    assert route(_pay_job(None, None, ""), 81, facts, cfg).bucket == BUCKET_APPLY


def test_pay_at_bar_passes(cfg, facts):
    cfg.routing.min_pay_lpa = 19.0
    assert route(_pay_job(1800000, 2500000), 81, facts, cfg).bucket == BUCKET_APPLY


def test_pay_non_inr_passes(cfg, facts):
    cfg.routing.min_pay_lpa = 19.0
    assert route(_pay_job(120000, 120000, "USD"), 81, facts, cfg).bucket == BUCKET_APPLY


def test_pay_gate_off_by_default(cfg, facts):
    assert route(_pay_job(800000, 1400000), 81, facts, cfg).bucket == BUCKET_APPLY