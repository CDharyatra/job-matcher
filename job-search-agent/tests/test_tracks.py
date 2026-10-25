from jobagent.matcher import build_rerank_pair, match_job
from jobagent.models import Job
from jobagent.resume import ResumeProfile
from jobagent.scoring import _score_with, score_deterministic, track_specs


def profile():
    return ResumeProfile(skills=["python", "django", "flask", "sql", "docker",
                                 "machine learning", "rag", "langchain"],
                         titles=["Machine Learning Engineer"])


def web_job():
    return Job(source="linkedin", title="Python Developer", company="WebCo",
               location="Bengaluru", apply_type="easy_apply",
               description_text=("Django and Flask web development with MySQL. "
                                 "Build REST APIs for customers. " * 8),
               experience_min=2, experience_max=4,
               posted_at="2026-09-28T08:00:00+00:00")


def test_track_specs_default_without_config(cfg, facts):
    cfg.search.tracks = []
    specs = track_specs(cfg)
    assert len(specs) == 1
    assert specs[0][1] == ["Senior Backend Engineer"]


def test_track_specs_from_config(cfg):
    cfg.search.tracks = [{"title": "Machine Learning Engineer", "skills": ["RAG"]},
                         {"title": "Python Developer", "skills": ["Django"]}]
    specs = track_specs(cfg)
    assert [s[0] for s in specs] == ["Machine Learning Engineer", "Python Developer"]


def test_python_web_job_uses_python_track(cfg, facts):
    cfg.search.must_have_skills = ["Python"]  # mirror real config: one universal must
    cfg.search.tracks = [
        {"title": "Machine Learning Engineer",
         "skills": ["Machine Learning", "RAG", "LangChain"]},
        {"title": "Python Developer",
         "skills": ["Python", "Django", "Flask", "REST API", "SQL"]},
    ]
    res = score_deterministic(web_job(), facts, cfg)
    assert res.track == "Python Developer"
    ml_only = _score_with(web_job(), facts, cfg, ["Machine Learning Engineer"],
                          ["Python"], ["Machine Learning", "RAG", "LangChain"])
    assert res.score >= ml_only.score


def test_ml_job_uses_ml_track(cfg, facts):
    cfg.search.must_have_skills = ["Python"]
    cfg.search.tracks = [
        {"title": "Machine Learning Engineer",
         "skills": ["Machine Learning", "RAG", "LangChain"]},
        {"title": "Python Developer",
         "skills": ["Python", "Django", "Flask", "REST API", "SQL"]},
    ]
    job = Job(source="linkedin", title="Machine Learning Engineer", company="AI",
              location="Bengaluru", apply_type="easy_apply",
              description_text=("Python RAG LangChain LLM production systems. " * 8),
              experience_min=2, experience_max=4,
              posted_at="2026-09-28T08:00:00+00:00")
    res = score_deterministic(job, facts, cfg)
    assert res.track == "Machine Learning Engineer"


def test_rerank_queries_per_track(cfg, facts):
    from jobagent.llm.rerank import RerankResult

    seen = []

    class FakeRerank:
        def score(self, query, passage, chain=None):
            seen.append(query)
            return RerankResult(ok=True, score=50.0, provider="t", model="m")

    cfg.search.must_have_skills = ["Python"]
    cfg.search.tracks = [
        {"title": "Machine Learning Engineer", "skills": ["RAG"]},
        {"title": "Python Developer", "skills": ["Django"]},
    ]
    job = web_job()
    cfg.llm.enabled = False
    match_job(job, 1, facts, cfg, profile(), llm=None, use_llm=False,
              rerank=FakeRerank())
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert "Python Developer" in seen[1]


def test_track_query_falls_back_to_profile(cfg, facts):
    q, _ = build_rerank_pair(profile(), facts, cfg, web_job())
    assert "python" in q.lower()