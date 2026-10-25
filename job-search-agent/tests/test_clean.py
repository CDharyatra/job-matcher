from jobagent.clean import is_blocklisted, is_obvious_spam
from jobagent.models import Job


def test_intern_does_not_match_internal_tools(cfg):
    cfg.blocklist = {"companies": [], "keywords": ["intern"]}
    job = Job(source="linkedin", title="Python Developer", company="Good",
              location="Bengaluru",
              description_text="Build internal tools and dashboards for the platform team.")
    blocked, _ = is_blocklisted(job, cfg)
    assert not blocked


def test_intern_matches_internship(cfg):
    cfg.blocklist = {"companies": [], "keywords": ["intern"]}
    job = Job(source="linkedin", title="ML Intern", company="X", location="Bengaluru",
              description_text="6-month internship, unpaid.")
    blocked, reason = is_blocklisted(job, cfg)
    assert blocked
    assert "intern" in reason


def test_spam_marker_word_boundary(cfg):
    # Partial-word overlap ("fee-payment") must not trip the "pay a fee" marker.
    job = Job(source="naukri", title="Fees Platform Engineer", company="X", location="Bengaluru",
              description_text=("Build the fee-payment reconciliation platform. " * 5))
    blocked, _ = is_obvious_spam(job)
    assert not blocked


def test_spam_marker_still_fires(cfg):
    job = Job(source="naukri", title="Earn From Home", company="X", location="Bengaluru",
              description_text=("Earn from home with no experience needed high salary. " * 3))
    blocked, reason = is_obvious_spam(job)
    assert blocked
    assert "spam marker" in reason