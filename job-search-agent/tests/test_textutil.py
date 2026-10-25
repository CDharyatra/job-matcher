from datetime import datetime, timezone

from jobagent.textutil import (
    canonical_city, canonical_skill, expand_title, parse_relative_date, parse_salary,
    parse_years, skill_present, title_tokens,
)


def test_salary_lpa():
    lo, hi, cur = parse_salary("18-24 LPA")
    assert (lo, hi, cur) == (1800000.0, 2400000.0, "INR")


def test_salary_single_lpa():
    lo, hi, cur = parse_salary("12.5 LPA")
    assert lo == hi == 1250000.0
    assert cur == "INR"


def test_salary_usd_range():
    lo, hi, cur = parse_salary("$120,000 - $150,000")
    assert lo == 120000.0 and hi == 150000.0 and cur == "USD"


def test_salary_not_disclosed():
    assert parse_salary("Not disclosed") == (None, None, "")


def test_relative_dates():
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    assert parse_relative_date("2 hours ago", now).startswith("2026-09-28T10:00")
    assert parse_relative_date("Reposted 3 days ago", now).startswith("2026-09-25T12:00")
    assert parse_relative_date("Just now", now).startswith("2026-09-28T12:00")
    assert parse_relative_date("2026-09-20", now).startswith("2026-09-20")


def test_years_band():
    assert parse_years("3-6 years") == (3.0, 6.0)
    assert parse_years("5+ years") == (5.0, None)
    assert parse_years("8-12 Yrs") == (8.0, 12.0)  # Naukri card shorthand
    assert parse_years("2-5 yrs") == (2.0, 5.0)
    assert parse_years("3+ yrs") == (3.0, None)


def test_skill_aliases_and_boundaries():
    assert skill_present("postgres", "we use postgresql daily")
    assert skill_present("kubernetes", "k8s cluster")
    # boundary: 'java' must not match 'javascript'
    assert not skill_present("java", "javascript developer")
    assert canonical_skill("k8s") == "kubernetes"


def test_skill_plural_matching():
    # resume writes plural, vocab lists singular (and vice versa)
    assert skill_present("websocket", "built with WebSockets and JWT")
    assert skill_present("webhook", "validated webhooks with Pydantic")
    assert skill_present("rest api", "developed REST APIs for analytics")
    # plural-forming never degrades short tokens
    assert not skill_present("aws", "awful weather today")
    assert skill_present("aws", "deployed on AWS Lambda")


def test_canonical_city():
    assert canonical_city("Bangalore") == "bengaluru"
    assert canonical_city("Bengaluru") == "bengaluru"
    assert canonical_city("  Gurgaon ") == "gurugram"
    assert canonical_city("Pune") == "pune"


def test_title_expansion():
    variants = expand_title("Senior Backend Engineer")
    assert any("back end" in v or "backend" in v for v in variants)
    assert title_tokens("Full-Stack Developer") & {"full", "stack", "developer"}