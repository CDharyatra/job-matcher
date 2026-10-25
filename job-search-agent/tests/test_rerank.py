import io
import json
import urllib.request

import pytest

from jobagent.config import LLMModel
from jobagent.llm.rerank import RerankClient


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(payload):
    return lambda req, timeout=None: FakeResp(payload)


def test_jina_parses_relevance(monkeypatch, cfg):
    monkeypatch.setattr(urllib.request, "urlopen",
                        fake_urlopen({"results": [{"relevance_score": 0.823}]}))
    monkeypatch.setenv("JINA_API_KEY", "test-key")
    import jobagent.llm.rerank as rr
    monkeypatch.setattr(rr, "get_secret", lambda k: "test-key")
    client = RerankClient(cfg)
    out = client._jina("m", "query", "passage")
    assert out.ok and out.score == 82.3


def test_cohere_parses(monkeypatch, cfg):
    monkeypatch.setattr(urllib.request, "urlopen",
                        fake_urlopen({"results": [{"relevance_score": 0.5}]}))
    import jobagent.llm.rerank as rr
    monkeypatch.setattr(rr, "get_secret", lambda k: "k")
    out = RerankClient(cfg)._cohere("m", "q", "p")
    assert out.ok and out.score == 50.0


def test_no_key_fails_soft(cfg):
    import jobagent.llm.rerank as rr
    orig = rr.get_secret
    rr.get_secret = lambda k: ""
    try:
        out = RerankClient(cfg)._jina("m", "q", "p")
        assert not out.ok and out.error == "no key"
    finally:
        rr.get_secret = orig


def test_chain_skips_paid_and_unknown(cfg):
    import jobagent.llm.rerank as rr
    monkeypatch_get = rr.get_secret
    client = RerankClient(cfg)
    chain = [LLMModel("cohere", "rerank-v3.5"), LLMModel("nope", "x")]
    rr.get_secret = lambda k: ""
    try:
        out = client.score("q", "p", chain=chain)
        assert not out.ok
    finally:
        rr.get_secret = monkeypatch_get


def test_local_bge_missing_deps_message(cfg, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = RerankClient(cfg)._local_bge("BAAI/bge-reranker-v2-m3", "q", "p")
    assert not out.ok
    assert "pip install" in out.error


def test_cache_hit_avoids_network(monkeypatch, cfg, tmp_path):
    from jobagent.database import Store
    store = Store(tmp_path / "r.sqlite3")
    client = RerankClient(cfg, store)

    def boom(req, timeout=None):
        raise AssertionError("network must not be hit on cache hit")

    store.cache_put("k", "77.0", "m")
    import jobagent.llm.rerank as rr
    real_hash = rr.text_hash
    rr.text_hash = lambda *a: "k"
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    try:
        out = client.score("q", "p", chain=[LLMModel("jina", "m")])
        assert out.ok and out.score == 77.0
    finally:
        rr.text_hash = real_hash


def test_budget_blocks(cfg, tmp_path):
    from jobagent.database import Store
    from datetime import datetime, timezone
    store = Store(tmp_path / "b.sqlite3")
    cfg.rerank.daily_budget_per_model = 0
    client = RerankClient(cfg, store)
    out = client.score("q", "p", chain=[LLMModel("jina", "m")])
    assert not out.ok


def test_build_pair_and_reference(cfg, facts):
    from jobagent.matcher import build_reference, build_rerank_pair
    from jobagent.models import Job
    from jobagent.resume import ResumeProfile
    profile = ResumeProfile(skills=["python", "aws"], titles=["ML Engineer"])
    job = Job(source="linkedin", title="ML Engineer", company="Acme",
              description_text="Python and AWS. " * 30)
    q, p = build_rerank_pair(profile, facts, cfg, job)
    assert "python" in q and "ML Engineer" in q
    assert "Acme" in p and len(p) <= 2000
    ref = build_reference(profile, facts)
    assert "ML Engineer" in ref and "python" in ref