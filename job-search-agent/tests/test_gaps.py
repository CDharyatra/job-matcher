from jobagent.digest import gaps_html
from jobagent.gaps import skill_gaps
from jobagent.models import Job
from jobagent.resume import ResumeProfile


def profile():
    return ResumeProfile(skills=["python", "aws"])


def scored_jobs():
    mk = lambda title, desc, score: (Job(
        source="linkedin", title=title, company="C", canonical_url=f"https://x/{title}",
        description_text=desc), score)
    return [
        mk("ML Engineer", "Python RAG LangChain Kubernetes role. " * 10, 85.0),
        mk("Backend Dev", "Python Docker Kubernetes microservices. " * 10, 72.0),
        mk("Java Dev", "Java Spring only role. " * 10, 30.0),  # below floor: ignored
    ]


def test_gaps_exclude_owned_skills():
    gaps = skill_gaps(scored_jobs(), profile(), top_n=10)
    skills = [g["skill"] for g in gaps]
    assert "python" not in skills
    assert "aws" not in skills
    assert "kubernetes" in skills
    assert "langchain" in skills or "rag" in skills


def test_gaps_ranked_by_demand():
    gaps = skill_gaps(scored_jobs(), profile(), top_n=10)
    counts = [g["jobs"] for g in gaps]
    assert counts == sorted(counts, reverse=True)
    k8s = next(g for g in gaps if g["skill"] == "kubernetes")
    assert k8s["jobs"] == 2


def test_gaps_empty_when_nothing_relevant():
    gaps = skill_gaps(scored_jobs(), ResumeProfile(skills=["python"]), top_n=0)
    assert gaps == []


def test_gaps_html_renders_and_empty():
    gaps = [{"skill": "kubernetes", "jobs": 12, "example": "ML Engineer"}]
    html = gaps_html(gaps)
    assert "kubernetes" in html and "12" in html and "upskill" in html
    assert gaps_html([]) == ""


def test_search_passes_default_both(cfg):
    from jobagent.browser.linkedin import search_passes
    cfg.platforms = {"linkedin": {"easy_apply_pass": True, "all_jobs_pass": True}}
    assert search_passes(cfg) == [True, False]
    cfg.platforms = {"linkedin": {"easy_apply_pass": True, "all_jobs_pass": False}}
    assert search_passes(cfg) == [True]
    cfg.platforms = {}
    assert search_passes(cfg) == [True, False]