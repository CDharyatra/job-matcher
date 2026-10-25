import pytest

from jobagent.llm import policy
from jobagent.llm.redact import build_redactor
from jobagent.facts import Facts


def test_refuses_paid_provider():
    with pytest.raises(policy.PaidModelError):
        policy.assert_free("openai", "gpt-5")


def test_refuses_paid_zen_model():
    with pytest.raises(policy.PaidModelError):
        policy.assert_free("opencode_zen", "deepseek-v4.1-flash")


def test_allows_free_zen_model():
    policy.assert_free("opencode_zen", "space-bunny-free")


def test_allows_nvidia_free_id():
    policy.assert_free("nvidia", "deepseek-ai/deepseek-v4.1-flash")


def test_circuit_breaker_skips_flapping_model(cfg):
    from jobagent.config import LLMModel
    from jobagent.llm.adapter import LLMClient, LLMResult
    client = LLMClient(cfg)
    calls = []

    def fail(*args):
        _self, provider, model, _prompt = args
        calls.append(model)
        return LLMResult(ok=False, provider=provider, model=model, error="Timeout")

    import jobagent.llm.adapter as ad
    orig = ad.LLMClient._call_with_retries
    ad.LLMClient._call_with_retries = fail
    try:
        chain = [LLMModel("nvidia", "deepseek-ai/deepseek-v4.1-flash")]
        for _ in range(5):
            out = client.complete_json("hi", chain=chain)
            assert not out.ok
        assert len(calls) == 3  # then circuit opens; no more attempts
    finally:
        ad.LLMClient._call_with_retries = orig


def test_circuit_resets_on_success(cfg):
    from jobagent.config import LLMModel
    from jobagent.llm.adapter import LLMClient, LLMResult
    client = LLMClient(cfg)
    state = {"fail": True}

    def flaky(*args):
        _self, provider, model, _prompt = args
        if state["fail"]:
            return LLMResult(ok=False, provider=provider, model=model, error="x")
        return LLMResult(ok=True, text="{}", model=model, provider=provider)

    import jobagent.llm.adapter as ad
    orig = ad.LLMClient._call_with_retries
    ad.LLMClient._call_with_retries = flaky
    try:
        chain = [LLMModel("nvidia", "deepseek-ai/deepseek-v4.1-flash")]
        client.complete_json("hi", chain=chain)
        client.complete_json("hi", chain=chain)
        state["fail"] = False
        out = client.complete_json("hi", chain=chain)
        assert out.ok
        assert client._consec_fail[("nvidia", "deepseek-ai/deepseek-v4.1-flash")] == 0
    finally:
        ad.LLMClient._call_with_retries = orig


def test_provider_pacing_sleeps_deficit(monkeypatch, cfg):
    import time as _time
    from jobagent.llm.adapter import LLMClient
    cfg.llm.provider_min_interval_seconds = {"groq_free": 40.0}
    client = LLMClient(cfg)
    slept = []
    monkeypatch.setattr(_time, "sleep", lambda s: slept.append(s))
    now = [1000.0]
    monkeypatch.setattr(_time, "monotonic", lambda: now[0])
    client._pace_provider("groq_free")  # first call: no wait
    assert slept == []
    now[0] = 1010.0  # 10s later: must wait 30s
    client._pace_provider("groq_free")
    assert slept == [30.0]
    client._pace_provider("nvidia")  # unconfigured provider: never waits
    assert slept == [30.0]


def test_allows_mistral_free():
    from jobagent.llm.adapter import _BASE_URLS, _KEY_ENV
    policy.assert_free("mistral_free", "mistral-large-latest")
    policy.assert_free("mistral_free", "mistral-small-latest")
    assert _BASE_URLS["mistral_free"] == "https://api.mistral.ai/v1"
    assert _KEY_ENV["mistral_free"] == "MISTRAL_API_KEY"


def test_refuses_paid_model_name_even_on_free_provider():
    with pytest.raises(policy.PaidModelError):
        policy.assert_free("opencode_zen", "kimi-k3")


def test_pii_safety_flags():
    assert not policy.is_pii_safe("nvidia", "deepseek-ai/deepseek-v4.1-flash")
    assert policy.is_pii_safe("opencode_zen", "space-bunny-free")
    assert not policy.is_pii_safe("opencode_zen", "muse-spark-1.3-contributor-free")


def test_redactor_strips_pii(facts):
    ident = facts.identity
    ident["full_name"] = "Dharyatra Chauhan"
    red = build_redactor(facts)
    text = ("Contact Dharyatra Chauhan at test@example.com or 9876543210. "
            "Portfolio https://example.com. Current CTC 18 LPA. Company Acme Corp.")
    out = red.redact(text)
    assert "Dharyatra" not in out
    assert "test@example.com" not in out
    assert "9876543210" not in out
    assert "https://example.com" not in out
    assert "Acme" not in out


def test_redactor_keeps_skills(facts):
    red = build_redactor(facts)
    out = red.redact("Python PostgreSQL AWS Docker")
    for s in ("Python", "PostgreSQL", "AWS", "Docker"):
        assert s in out


def test_no_pan_or_aadhaar(facts):
    red = build_redactor(facts)
    assert "ABCDE1234F" not in red.redact("PAN ABCDE1234F")
    assert "1234 5678 9012" not in red.redact("Aadhaar 1234 5678 9012")