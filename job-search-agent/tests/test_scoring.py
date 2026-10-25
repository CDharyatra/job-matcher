from jobagent.models import Job
from jobagent.scoring import score_deterministic


def test_strong_match_scores_high(cfg, facts):
    job = Job(
        source="linkedin", title="Senior Backend Engineer", company="Good",
        location="Bengaluru", apply_type="easy_apply",
        description_text=("We need a Python backend engineer with PostgreSQL, AWS, Docker, "
                          "and Kubernetes. 4-8 years experience. REST API microservices."),
        requirements="Python PostgreSQL AWS", salary_raw="30-40 LPA",
        experience_min=4, experience_max=8,
        posted_at="2026-09-28T08:00:00+00:00",
    )
    r = score_deterministic(job, facts, cfg)
    assert r.score >= 70
    assert not r.must_miss


def test_missing_must_have_hard_caps(cfg, facts):
    job = Job(
        source="linkedin", title="Java Backend Engineer", company="Bad",
        location="Bengaluru", description_text="Java Spring Boot only. No Python.",
        requirements="Java Spring", experience_min=4, experience_max=8,
        posted_at="2026-09-28T08:00:00+00:00",
    )
    r = score_deterministic(job, facts, cfg)
    assert r.hard_cap
    assert r.score <= 55


def test_negative_keyword_hard_caps(cfg, facts):
    job = Job(source="linkedin", title="Backend Engineer", company="X",
              location="Bengaluru", description_text="Python backend intern wordpress role",
              posted_at="2026-09-28T08:00:00+00:00")
    r = score_deterministic(job, facts, cfg)
    assert r.hard_cap
    assert r.score <= 55


def test_bangalore_matches_bengaluru_target(cfg, facts):
    job = Job(
        source="linkedin", title="Senior Backend Engineer", company="Good",
        location="Bangalore, Karnataka", apply_type="easy_apply",
        description_text=("We need a Python backend engineer with PostgreSQL, AWS, Docker. "
                          "4-8 years experience building REST API microservices."),
        requirements="Python PostgreSQL AWS", salary_raw="30-40 LPA",
        experience_min=4, experience_max=8,
        posted_at="2026-09-28T08:00:00+00:00",
    )
    r = score_deterministic(job, facts, cfg)
    assert not any("location not in" in reason for reason in r.reasons)
    assert r.score >= 70


def test_must_have_misses_reported(cfg, facts):
    job = Job(source="linkedin", title="Backend Engineer", company="X", location="Bengaluru",
              description_text="Python only", posted_at="2026-09-28T08:00:00+00:00")
    r = score_deterministic(job, facts, cfg)
    assert "postgresql" in r.must_miss or "aws" in r.must_miss