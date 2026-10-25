import json

from jobagent.llm.adapter import LLMResult
from jobagent.matcher import match_job
from jobagent.models import Job
from jobagent.resume import ResumeProfile


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, prompt, chain=None, allow_pii=False):
        return LLMResult(ok=True, text=json.dumps(self.payload),
                         model="deepseek-ai/deepseek-v4.1-flash", provider="nvidia")


def good_job():
    return Job(source="linkedin", title="Senior Backend Engineer", company="Good",
               location="Bengaluru", apply_type="easy_apply",
               description_text=("We need a Python backend engineer with PostgreSQL, AWS, Docker, "
                                 "Kubernetes and REST APIs. You will design microservices, own CI/CD, "
                                 "and mentor juniors. 4-8 years of backend experience required."),
               experience_min=4, experience_max=8, posted_at="2026-09-28T08:00:00+00:00")


def test_no_description_means_deterministic_only(cfg, facts):
    job = good_job()
    job.description_text = "Python backend"  # too thin for the judge
    llm = FakeLLM({
        "overall_match": 84, "must_have_hits": ["python"], "must_have_misses": [],
        "evidence": [{"requirement": "Python", "resume_signal": "present", "match": True}],
        "rationale": "x",
    })
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True)
    assert not res.llm_used
    assert res.llm_score is None


def profile():
    return ResumeProfile(skills=["python", "postgresql", "aws", "docker", "kubernetes"],
                         titles=["Senior Backend Engineer"])


def test_deterministic_only_when_llm_down(cfg, facts):
    job = good_job()
    res = match_job(job, 1, facts, cfg, profile(), llm=None, use_llm=False)
    assert res.overall_match == res.deterministic_score
    assert res.llm_score is None


def test_llm_evidence_fusion(cfg, facts):
    job = good_job()
    llm = FakeLLM({
        "overall_match": 84, "must_have_hits": ["python", "postgresql", "aws"],
        "must_have_misses": [],
        "evidence": [{"requirement": "Python", "resume_signal": "5y Python", "match": True}],
        "resume_version_suggestion": "default", "rationale": "strong backend fit",
    })
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True)
    assert res.llm_used
    assert 70 <= res.overall_match <= 90
    assert res.decision.bucket == "A_autoapply"


def test_llm_invalid_evidence_rejected(cfg, facts):
    job = good_job()
    llm = FakeLLM({"overall_match": 95, "evidence": [], "must_have_misses": []})
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True)
    # rejected output -> deterministic only, no llm score
    assert res.llm_score is None
    assert not res.llm_used


def test_hard_cap_beats_llm(cfg, facts):
    job = Job(source="linkedin", title="Java Engineer", company="X", location="Bengaluru",
              description_text="Java Spring only", apply_type="easy_apply",
              posted_at="2026-09-28T08:00:00+00:00")
    llm = FakeLLM({
        "overall_match": 88, "must_have_hits": [], "must_have_misses": ["python"],
        "evidence": [{"requirement": "Java", "resume_signal": "generic", "match": True}],
        "rationale": "x",
    })
    # schema says must-have miss + score > 55 is invalid, so it's rejected -> deterministic cap
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True)
    assert res.overall_match <= 55


def test_judge_calls_are_logged(cfg, facts, caplog):
    import logging
    job = good_job()
    llm = FakeLLM({
        "overall_match": 84, "must_have_hits": ["python"], "must_have_misses": [],
        "evidence": [{"requirement": "Python", "resume_signal": "present", "match": True}],
        "rationale": "x",
    })
    with caplog.at_level(logging.INFO, logger="jobagent.matcher"):
        match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True)
    assert any("judge" in r.message and "84" in r.message for r in caplog.records)


class FakeRerank:
    def __init__(self, score):
        self._score = score
        self.calls = 0

    def score(self, query, passage, chain=None):
        from jobagent.llm.rerank import RerankResult
        self.calls += 1
        return RerankResult(ok=True, score=self._score,
                            provider="jina", model="m")


def test_rerank_fusion_and_band(cfg, facts):
    job = good_job()
    llm = FakeLLM({
        "overall_match": 84, "must_have_hits": ["python"], "must_have_misses": [],
        "evidence": [{"requirement": "Python", "resume_signal": "present", "match": True}],
        "rationale": "x",
    })
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True,
                    rerank=FakeRerank(80.0))
    assert res.rerank_score == 80.0
    assert res.llm_used  # prelim 88.1 inside [60, 93]
    # 0.5*84 + 0.3*80 + 0.2*det
    assert res.overall_match == round(0.5 * 84 + 0.3 * 80 + 0.2 * res.deterministic_score, 1)


def test_rerank_above_band_skips_llm(cfg, facts):
    job = good_job()
    llm = FakeLLM({"overall_match": 99, "must_have_hits": [], "must_have_misses": [],
                   "evidence": [{"requirement": "x", "resume_signal": "y", "match": True}],
                   "rationale": "x"})
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True,
                    rerank=FakeRerank(99.0))
    assert not res.llm_used
    assert res.overall_match > 93


def test_rerank_below_band_discards_without_llm(cfg, facts):
    job = good_job()
    llm = FakeLLM({"overall_match": 90, "must_have_hits": [], "must_have_misses": [],
                   "evidence": [{"requirement": "x", "resume_signal": "y", "match": True}],
                   "rationale": "x"})
    rr = FakeRerank(10.0)
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True, rerank=rr)
    assert not res.llm_used
    assert res.decision.bucket == "C_discard"


def test_hard_cap_skips_rerank(cfg, facts):
    job = Job(source="linkedin", title="Java Engineer", company="X", location="Bengaluru",
              description_text="Java Spring only", apply_type="easy_apply",
              posted_at="2026-09-28T08:00:00+00:00")
    rr = FakeRerank(95.0)
    res = match_job(job, 1, facts, cfg, profile(), llm=None, use_llm=False, rerank=rr)
    assert rr.calls == 0
    assert res.rerank_score is None
    assert res.overall_match <= 55


def test_llm_overoptimism_tempered(cfg, facts):
    job = good_job()
    llm = FakeLLM({
        "overall_match": 100, "must_have_hits": ["python"], "must_have_misses": [],
        "evidence": [{"requirement": "Python", "resume_signal": "present", "match": True}],
        "rationale": "x",
    })
    res = match_job(job, 1, facts, cfg, profile(), llm=llm, use_llm=True)
    assert res.overall_match <= res.deterministic_score + 20