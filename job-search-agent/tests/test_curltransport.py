import json
import subprocess

from jobagent.llm import curltransport as ct


class Done:
    def __init__(self, stdout):
        self.stdout = stdout.encode()
        self.returncode = 0


def test_post_success(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: Done('{"a": 1}\n200'))
    status, payload = ct.curl_post_json("https://x", {"q": 1}, {"H": "v"}, 10)
    assert (status, payload) == (200, {"a": 1})


def test_post_non_json_body(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: Done('oops\n502'))
    status, payload = ct.curl_post_json("https://x", {}, {}, 10)
    assert status == 502 and payload == "oops"


def test_post_timeout_propagates(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="curl", timeout=10)

    monkeypatch.setattr(subprocess, "run", boom)
    import pytest
    with pytest.raises(subprocess.TimeoutExpired):
        ct.curl_post_json("https://x", {}, {}, 10)


def test_get_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: Done('{"data": []}\n200'))
    status, payload = ct.curl_get_json("https://x", {}, 10)
    assert (status, payload) == (200, {"data": []})


def test_adapter_zen_uses_curl(monkeypatch, cfg):
    from jobagent.llm.adapter import LLMClient
    monkeypatch.setattr(ct, "curl_available", lambda: True)
    monkeypatch.setattr(ct, "curl_post_json",
                        lambda *a, **k: (200, {"choices": [
                            {"message": {"content": '{"overall_match": 1}'}}]}))
    client = LLMClient(cfg)
    res = client._call_with_retries(
        "opencode_zen", "space-bunny-free", '{"overall_match": 1}')
    assert res.ok and res.text == '{"overall_match": 1}'


def test_adapter_zen_429_maps(monkeypatch, cfg):
    from jobagent.llm.adapter import LLMClient
    monkeypatch.setattr(ct, "curl_available", lambda: True)
    monkeypatch.setattr(ct, "curl_post_json", lambda *a, **k: (429, None))
    client = LLMClient(cfg)
    res = client._call_with_retries("opencode_zen", "space-bunny-free", "hi")
    assert not res.ok and res.rate_limited and res.error == "429"


def _http403():
    import io
    import urllib.error
    return urllib.error.HTTPError("https://x", 403, "Forbidden", {}, io.BytesIO(b"nope"))


def test_403_falls_back_to_curl(monkeypatch, cfg):
    import urllib.request
    from jobagent.llm.adapter import LLMClient

    def boom(req, timeout=None):
        raise _http403()

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(ct, "curl_post_json",
                        lambda *a, **k: (200, {"choices": [
                            {"message": {"content": "curl-saved"}}]}))
    res = LLMClient(cfg)._call_with_retries("groq_free", "qwen/qwen3.8-27b", "{}")
    assert res.ok and res.text == "curl-saved"


def test_403_stays_403_when_curl_also_refused(monkeypatch, cfg):
    import urllib.request
    from jobagent.llm.adapter import LLMClient

    def boom(req, timeout=None):
        raise _http403()

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(ct, "curl_post_json", lambda *a, **k: (403, None))
    res = LLMClient(cfg)._call_with_retries("groq_free", "qwen/qwen3.8-27b", "{}")
    assert not res.ok and res.error == "HTTP 403"


def test_list_models_falls_back_to_curl(monkeypatch, cfg):
    import urllib.request
    import jobagent.llm.adapter as ad

    def boom(req, timeout=None):
        raise _http403()

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(ct, "curl_get_json",
                        lambda *a, **k: (200, {"data": [{"id": "qwen/qwen3.8-27b"}]}))
    monkeypatch.setattr(ad.LLMClient, "_key", lambda self, p: "k")
    assert ad.LLMClient(cfg).list_models("groq_free") == ["qwen/qwen3.8-27b"]


def test_adapter_zen_list_models(monkeypatch, cfg):
    from jobagent.llm.adapter import LLMClient
    monkeypatch.setattr(ct, "curl_available", lambda: True)
    monkeypatch.setattr(ct, "curl_get_json",
                        lambda *a, **k: (200, {"data": [{"id": "space-bunny-free"}]}))
    import jobagent.llm.adapter as ad
    monkeypatch.setattr(ad.LLMClient, "_key", lambda self, p: "k")
    assert LLMClient(cfg).list_models("opencode_zen") == ["space-bunny-free"]
