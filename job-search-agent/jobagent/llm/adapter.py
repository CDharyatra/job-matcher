"""Model-agnostic OpenAI chat adapter with cache, budget, backoff, failover.

Guarantees:
  - only $0 providers/models (policy.assert_free);
  - PII-redacted before send;
  - per-model daily budget (NVIDIA free limits are undocumented, so we self-cap);
  - exponential backoff + jitter on 429/5xx;
  - failover down the configured chain, ending at deterministic (no-op here).
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import urllib.error
import urllib.request

from .. import paths
from ..config import LLMModel, load_config, get_secret, Config
from ..logging_setup import get_logger, scrub
from . import policy
from .redact import Redactor

log = get_logger("jobagent.llm")

_BASE_URLS = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "opencode_zen": "https://opencode.ai/zen/v1",
    "openrouter_free": "https://openrouter.ai/api/v1",
    "groq_free": "https://api.groq.com/openai/v1",
    "mistral_free": "https://api.mistral.ai/v1",
}
_KEY_ENV = {
    "nvidia": "NVIDIA_API_KEY",
    "opencode_zen": "OPENCODE_ZEN_API_KEY",
    "openrouter_free": "OPENROUTER_API_KEY",
    "groq_free": "GROQ_API_KEY",
    "mistral_free": "MISTRAL_API_KEY",
}


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    model: str = ""
    provider: str = ""
    cached: bool = False
    error: str = ""
    rate_limited: bool = False


class _HTTPStatus(Exception):
    """Non-2xx from transports (curl) that don't raise urllib-style errors."""

    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.code = code


class LLMClient:
    # After this many consecutive failures, a model is skipped for the rest
    # of the process: a stalled endpoint must not burn minutes on every job.
    CIRCUIT_THRESHOLD = 3

    def __init__(self, config: Config | None = None, store=None):
        self.config = config or load_config()
        self.store = store
        self.redactor = Redactor()
        self._consec_fail: dict[tuple[str, str], int] = {}

    def set_redactor(self, redactor: Redactor) -> None:
        self.redactor = redactor

    def _day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _key(self, provider: str) -> str:
        return get_secret(_KEY_ENV.get(provider, ""))

    def _cache_key(self, provider: str, model: str, prompt: str) -> str:
        from ..textutil import text_hash
        return text_hash(provider, model, self.config.llm.prompt_version, prompt)

    def complete_json(
        self,
        prompt: str,
        chain: list[LLMModel] | None = None,
        allow_pii: bool = False,
    ) -> LLMResult:
        """Send a prompt expecting a JSON object response, walking the chain."""
        if not self.config.llm.enabled:
            return LLMResult(ok=False, error="llm disabled")
        chain = chain or self.config.llm.judge_chain
        safe_prompt = prompt if allow_pii else self.redactor.redact(prompt)

        for model_cfg in chain:
            provider, model = model_cfg.provider, model_cfg.model
            try:
                policy.assert_free(provider, model)
            except policy.PaidModelError as e:
                log.error("refusing paid model: %s", e)
                continue

            if not allow_pii and not policy.is_pii_safe(provider, model):
                # still allowed, but the prompt is already redacted
                pass

            ck = self._cache_key(provider, model, safe_prompt)
            if self.store:
                hit = self.store.cache_get(ck)
                if hit is not None:
                    return LLMResult(ok=True, text=hit, model=model, provider=provider, cached=True)

            if self.store and self.store.usage_get(self._day(), provider, model) >= self.config.llm.daily_call_budget_per_model:
                log.warning("daily budget reached for %s/%s", provider, model)
                continue
            if self._consec_fail.get((provider, model), 0) >= self.CIRCUIT_THRESHOLD:
                log.warning("circuit open for %s/%s (%d consecutive failures); skipping",
                            provider, model, self.CIRCUIT_THRESHOLD)
                continue

            result = self._call_with_retries(provider, model, safe_prompt)
            if result.ok:
                self._consec_fail[(provider, model)] = 0
                if self.store:
                    self.store.cache_put(ck, result.text, model)
                return result
            self._consec_fail[(provider, model)] = self._consec_fail.get((provider, model), 0) + 1
            if result.rate_limited:
                log.warning("rate limited on %s/%s, failing over", provider, model)
                continue

        return LLMResult(ok=False, error="all models exhausted -> deterministic only")

    def _call_with_retries(self, provider: str, model: str, prompt: str) -> LLMResult:
        key = self._key(provider)
        if not key:
            return LLMResult(ok=False, provider=provider, model=model, error=f"no key for {provider}")
        self._pace_provider(provider)

        url = _BASE_URLS[provider].rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "You reply with a single valid JSON object. No prose."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        # Cloudflare bot-management blocks urllib's TLS fingerprint on some
        # hosts; those providers go curl-first (urllib would 403 every call
        # before the retry). opencode_zen always needed it; groq_free joined
        # after its edge started 403ing urllib on every judge call.
        use_curl = provider in ("opencode_zen", "groq_free")
        if use_curl:
            from .curltransport import curl_available
            use_curl = curl_available()
            if not use_curl:
                log.warning("curl binary missing; zen calls will likely 403")

        for attempt in range(self.config.llm.max_retries + 1):
            try:
                if use_curl:
                    code, payload = self._curl_chat(url, key, json.loads(body.decode("utf-8")))
                else:
                    req = urllib.request.Request(url, data=body, method="POST")
                    req.add_header("Content-Type", "application/json")
                    req.add_header("Authorization", f"Bearer {key}")
                    with urllib.request.urlopen(req, timeout=self.config.llm.request_timeout_seconds) as resp:
                        code, payload = resp.status, json.loads(resp.read().decode("utf-8"))
                if code == 429:
                    if self.store:
                        self.store.usage_inc(self._day(), provider, model, "rate_limited")
                    return LLMResult(ok=False, provider=provider, model=model,
                                     error="429", rate_limited=True)
                if code != 200:
                    raise _HTTPStatus(code)
                text = payload["choices"][0]["message"]["content"]
                if self.store:
                    self.store.usage_inc(self._day(), provider, model, "calls")
                return LLMResult(ok=True, text=text, model=model, provider=provider)
            except urllib.error.HTTPError as e:
                code = e.code
                if code == 403 and not use_curl:
                    # Cloudflare bot-management blocks urllib's TLS fingerprint
                    # on some hosts (1010) while curl passes. One curl attempt
                    # distinguishes fingerprinting (curl 200s) from bad auth.
                    retried = self._retry_403_via_curl(
                        url, key, json.loads(body.decode("utf-8")),
                        provider, model)
                    if retried is not None:
                        return retried
                if self.store:
                    self.store.usage_inc(self._day(), provider, model, "errors")
                if code == 429:
                    if self.store:
                        self.store.usage_inc(self._day(), provider, model, "rate_limited")
                    return LLMResult(ok=False, provider=provider, model=model,
                                     error="429", rate_limited=True)
                if code in (500, 502, 503, 504) and attempt < self.config.llm.max_retries:
                    self._sleep(attempt)
                    continue
                return LLMResult(ok=False, provider=provider, model=model, error=f"HTTP {code}")
            except _HTTPStatus as e:
                if self.store:
                    self.store.usage_inc(self._day(), provider, model, "errors")
                if e.code in (500, 502, 503, 504) and attempt < self.config.llm.max_retries:
                    self._sleep(attempt)
                    continue
                return LLMResult(ok=False, provider=provider, model=model,
                                 error=f"HTTP {e.code}")
            except Exception as e:  # noqa: BLE001 - network/timeout
                if attempt < self.config.llm.max_retries:
                    self._sleep(attempt)
                    continue
                return LLMResult(ok=False, provider=provider, model=model, error=scrub(str(e)))
        return LLMResult(ok=False, provider=provider, model=model, error="exhausted retries")

    @staticmethod
    def _curl_chat(url: str, key: str, body: dict) -> tuple[int, dict]:
        from .curltransport import curl_post_json
        return curl_post_json(url, body, {"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"}, 60)

    def _retry_403_via_curl(self, url: str, key: str, body: dict,
                            provider: str, model: str) -> LLMResult | None:
        """One curl attempt after a urllib 403. Returns None to keep the 403."""
        from .curltransport import curl_available
        if not curl_available():
            return None
        log.warning("urllib 403 on %s/%s; retrying via curl transport",
                    provider, model)
        try:
            code, payload = self._curl_chat(url, key, body)
        except Exception as e:  # noqa: BLE001
            return LLMResult(ok=False, provider=provider, model=model,
                             error=scrub(str(e)))
        if code == 429:
            if self.store:
                self.store.usage_inc(self._day(), provider, model, "rate_limited")
            return LLMResult(ok=False, provider=provider, model=model,
                             error="429", rate_limited=True)
        if code != 200:
            return None  # genuine refusal (e.g. bad key); keep original 403
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return LLMResult(ok=False, provider=provider, model=model,
                             error="bad payload")
        if self.store:
            self.store.usage_inc(self._day(), provider, model, "calls")
        return LLMResult(ok=True, text=text, model=model, provider=provider)

    def _sleep(self, attempt: int) -> None:
        base = self.config.llm.backoff_base_seconds
        delay = base * (2 ** attempt) + random.uniform(0, 1.0)
        time.sleep(delay)

    def _pace_provider(self, provider: str) -> None:
        """Sleep so calls to one provider stay under its per-minute quota."""
        interval = float((self.config.llm.provider_min_interval_seconds or {}).get(provider, 0) or 0)
        if interval <= 0:
            return
        if not hasattr(self, "_last_provider_call"):
            self._last_provider_call = {}
        wait = interval - (time.monotonic() - self._last_provider_call.get(provider, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_provider_call[provider] = time.monotonic()

    def list_models(self, provider: str = "nvidia") -> list[str]:
        key = self._key(provider)
        if not key:
            return []
        url = _BASE_URLS[provider].rstrip("/") + "/models"
        try:
            if provider == "opencode_zen":
                from .curltransport import curl_available, curl_get_json
                if not curl_available():
                    log.error("list_models needs the curl binary for %s", provider)
                    return []
                _code, payload = curl_get_json(
                    url, {"Authorization": f"Bearer {key}"}, 30)
            else:
                req = urllib.request.Request(url)
                req.add_header("Authorization", f"Bearer {key}")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            return [m.get("id", "") for m in payload.get("data", [])]
        except urllib.error.HTTPError as e:
            if e.code == 403:
                from .curltransport import curl_available, curl_get_json
                if curl_available():
                    try:
                        _code, payload = curl_get_json(
                            url, {"Authorization": f"Bearer {key}"}, 30)
                        return [m.get("id", "") for m in payload.get("data", [])]
                    except Exception:  # noqa: BLE001
                        pass
            log.error("list_models failed for %s: HTTP %s", provider, e.code)
            return []
        except Exception as e:  # noqa: BLE001
            log.error("list_models failed for %s: %s", provider, scrub(str(e)))
            return []