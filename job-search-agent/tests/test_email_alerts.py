from jobagent.digest import build_digest, packet_html, prioritize
from jobagent.mail.alerts import parse_email
from jobagent.mail.reader import RawEmail
from jobagent.matcher import MatchResult
from jobagent.clean import RouteDecision, BUCKET_INBOX
from jobagent.models import Job


def test_linkedin_alert_parsing():
    html = ('<a href="https://www.linkedin.com/jobs/view/12345?trk=email">'
            'Senior Backend Engineer</a> Please apply now')
    raw = RawEmail(uid="1", subject="New jobs for you", sender="jobs@linkedin.com",
                   html=html, text="")
    jobs = parse_email(raw)
    assert jobs
    assert jobs[0].source == "linkedin"
    assert "12345" in jobs[0].canonical_url


def test_naukri_alert_parsing():
    html = ('<a href="https://www.naukri.com/job-listings-backend-engineer-acme-123456">'
            'Backend Engineer</a>')
    raw = RawEmail(uid="2", subject="Jobs matching your profile", sender="info@naukri.com",
                   html=html, text="")
    jobs = parse_email(raw)
    assert jobs
    assert jobs[0].source == "naukri"


def test_naukri_tracking_redirect_unwrapped():
    import urllib.parse
    dest = ("https://naukri.com/job-listings-senior-ai-ml-engineer-llm-rag-and-agentic-ai-"
            "optum-global-solutions-india-private-limited-bengaluru-2-to-7-years-"
            "011026927484?utm_campaign=x")
    href = ("https://tr.naukri.com?data=%7B%22eventCode%22%3A%221%22%7D"
            "&redirect=" + urllib.parse.quote(dest, safe=""))
    html = (f'<a href="{href}">Senior AI/ML Engineer - LLM, RAG and Agentic AI</a>'
            f'<a href="{href}">Senior AI/ML Engineer - LLM, RAG and Agentic AI</a>')
    raw = RawEmail(uid="3", subject="9 Jobs in your JobMail", sender="jobmail@naukri.com",
                   html=html, text="")
    jobs = parse_email(raw)
    assert len(jobs) == 1  # duplicate tracking links deduped
    job = jobs[0]
    assert job.source == "naukri"
    assert job.source_job_id == "011026927484"
    assert (job.experience_min, job.experience_max) == (2.0, 7.0)
    assert "utm_campaign" not in job.canonical_url
    assert "Senior AI/ML Engineer" in job.title


def test_alert_intake_disabled_by_default(cfg):
    assert cfg.email.alert_intake_enabled is False


def test_digest_renders(facts):
    job = Job(source="linkedin", title="Senior Backend Engineer", company="Good",
              location="Bengaluru", apply_type="easy_apply", canonical_url="https://x",
              posted_at="2026-09-28T08:00:00+00:00", salary_raw="30-40 LPA")
    res = MatchResult(job_id=1, overall_match=85, deterministic_score=80, llm_score=88,
                      decision=RouteDecision(BUCKET_INBOX, "external", []),
                      reasons=["title match"], evidence=[{"requirement": "Python", "resume_signal": "5y"}],
                      resume_used="default")
    html, text = build_digest("run1", [(job, res)], [], [], {"inbox": 1})
    assert "Senior Backend Engineer" in html
    assert "https://x" in html
    assert "Job Agent" in html
    assert "DRY RUN" not in html


def _item(score, posted="2026-09-28T08:00:00+00:00"):
    from jobagent.clean import BUCKET_INBOX, RouteDecision
    from jobagent.matcher import MatchResult
    from jobagent.models import Job
    job = Job(source="linkedin", title=f"Job {score}", company="C",
              canonical_url=f"https://x/{score}", posted_at=posted)
    res = MatchResult(job_id=score, overall_match=score, deterministic_score=score,
                      llm_score=None, decision=RouteDecision(BUCKET_INBOX, "x", []),
                      reasons=[], evidence=[], resume_used="default")
    return job, res


def test_prioritize_best_first_with_overflow():
    items = [_item(s) for s in (70, 95, 80, 92, 75)]
    top, overflow = prioritize(items, 2)
    assert [r.overall_match for _, r in top] == [95, 92]
    assert overflow == 3


def test_prioritize_recency_breaks_ties():
    items = [_item(85, "2026-09-20T08:00:00+00:00"),
             _item(85, "2026-09-28T08:00:00+00:00")]
    top, overflow = prioritize(items, 2)
    assert top[0][0].posted_at.startswith("2026-09-28")
    assert overflow == 0


def test_packet_dry_run_banner(facts):
    job = Job(source="linkedin", title="T", company="C", canonical_url="u")
    res = MatchResult(1, 80, 80, None, RouteDecision("A_autoapply", "x", []), [], [], "default")
    html = packet_html(job, res, dry_run=True)
    assert "DRY RUN" in html