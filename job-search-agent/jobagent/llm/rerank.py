"""Cross-encoder rerank scoring: the fast, accurate pairwise relevance signal.

Why this exists (see docs/MODELS.md): for single (candidate, job) scoring,
joint cross-attention beats embedding cosine (MS MARCO: +27% relative) and costs
one forward pass versus an LLM judge's seconds of generation. The LLM judge is
kept for borderline cases and evidence prose; the reranker carries the score.

Providers are all $0 (policy.assert_free): Jina (10M free tokens), Voyage (200M
one-time), Cohere trial (1k calls/month — kept last as an audit reserve), and a
local bge-reranker (zero network, zero key, needs torch). Missing keys or deps
fail soft instantly — never an exception, never a payment.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

from ..config import get_secret
from ..logging_setup import get_logger, scrub
from ..textutil import text_hash
from . import policy

log = get_logger("jobagent.rerank")

_KEY_ENV = {
    "jina": "JINA_API_KEY",
    "cohere": "COHERE_API_KEY",
    "voyage": "VOYAGE_API_KEY",
    "local_bge": "",
}


@dataclass
class RerankResult:
    ok: bool
    score: float | None = None  # 0-100
    provider: str = ""
    model: str = ""
    error: str = ""


def _post(url: str, body: dict, key: str, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class RerankClient:
    def __init__(self, config=None, store=None):
        from ..config import load_config
        self.config = config or load_config()
        self.store = store

    @property
    def _rc(self):
        return self.config.rerank

    def _budget_ok(self, provider: str, model: str) -> bool:
        if not self.store:
            return True
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.store.usage_get(day, f"rerank:{provider}", model) < self._rc.daily_budget_per_model

    def _budget_use(self, provider: str, model: str) -> None:
        if not self.store:
            return
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.store.usage_inc(day, f"rerank:{provider}", model, "calls")

    def score(self, query: str, passage: str, chain=None) -> RerankResult:
        """Score one (candidate, job) pair 0-100. Walks the chain, fail-soft."""
        if not self._rc.enabled:
            return RerankResult(ok=False, error="rerank disabled")
        chain = chain if chain is not None else self._rc.chain
        for model_cfg in chain:
            provider, model = model_cfg.provider, model_cfg.model
            try:
                policy.assert_free(provider, model)
            except policy.PaidModelError as e:
                log.error("refusing paid rerank model: %s", e)
                continue
            if not self._budget_ok(provider, model):
                continue
            ck = text_hash("rerank", provider, model, query[:2000], passage[:4000])
            if self.store:
                hit = self.store.cache_get(ck)
                if hit is not None:
                    try:
                        return RerankResult(ok=True, score=float(hit),
                                            provider=provider, model=model)
                    except ValueError:
                        pass
            fn = {"jina": self._jina, "cohere": self._cohere,
                  "voyage": self._voyage, "local_bge": self._local_bge}.get(provider)
            if fn is None:
                continue
            try:
                result = fn(model, query, passage)
            except Exception as e:  # noqa: BLE001 - failover, never crash
                log.warning("rerank %s/%s failed: %s: %s", provider, model,
                            type(e).__name__, scrub(str(e)))
                continue
            if result.ok and result.score is not None:
                self._budget_use(provider, model)
                if self.store:
                    self.store.cache_put(ck, str(result.score), model)
                return result
        return RerankResult(ok=False, error="all rerank providers exhausted")

    # ---- providers ------------------------------------------------------
    def _jina(self, model: str, query: str, passage: str) -> RerankResult:
        key = get_secret(_KEY_ENV["jina"])
        if not key:
            return RerankResult(ok=False, provider="jina", model=model, error="no key")
        payload = _post("https://api.jina.ai/v1/rerank",
                        {"model": model, "query": query,
                         "documents": [passage], "top_n": 1}, key, timeout=30)
        results = payload.get("results") or payload.get("data") or []
        if not results:
            return RerankResult(ok=False, provider="jina", model=model, error="empty")
        s = results[0].get("relevance_score", results[0].get("score"))
        return RerankResult(ok=True, score=round(float(s) * 100, 1),
                            provider="jina", model=model)

    def _cohere(self, model: str, query: str, passage: str) -> RerankResult:
        key = get_secret(_KEY_ENV["cohere"])
        if not key:
            return RerankResult(ok=False, provider="cohere", model=model, error="no key")
        payload = _post("https://api.cohere.com/v2/rerank",
                        {"model": model, "query": query,
                         "documents": [passage], "top_n": 1}, key, timeout=30)
        results = payload.get("results") or []
        if not results:
            return RerankResult(ok=False, provider="cohere", model=model, error="empty")
        return RerankResult(ok=True, score=round(float(results[0]["relevance_score"]) * 100, 1),
                            provider="cohere", model=model)

    def _voyage(self, model: str, query: str, passage: str) -> RerankResult:
        key = get_secret(_KEY_ENV["voyage"])
        if not key:
            return RerankResult(ok=False, provider="voyage", model=model, error="no key")
        payload = _post("https://api.voyageai.com/v1/rerank",
                        {"model": model, "query": query,
                         "documents": [passage], "top_k": 1}, key, timeout=30)
        data = payload.get("data") or []
        if not data:
            return RerankResult(ok=False, provider="voyage", model=model, error="empty")
        return RerankResult(ok=True, score=round(float(data[0]["relevance_score"]) * 100, 1),
                            provider="voyage", model=model)

    _encoders: dict = {}

    def _local_bge(self, model: str, query: str, passage: str) -> RerankResult:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            return RerankResult(ok=False, provider="local_bge", model=model,
                                error="needs: pip install torch --index-url "
                                      "https://download.pytorch.org/whl/cpu "
                                      "transformers sentence-transformers")
        name = model or "BAAI/bge-reranker-v2-m3"
        if name not in RerankClient._encoders:
            t0 = time.monotonic()
            RerankClient._encoders[name] = CrossEncoder(name, max_length=512)
            log.info("local_bge loaded %s in %.1fs", name, time.monotonic() - t0)
        t0 = time.monotonic()
        logit = float(RerankClient._encoders[name].predict(
            [(query, passage)], normalize=True)[0])
        log.info("local_bge %.1fs | %.1f", time.monotonic() - t0, logit * 100)
        return RerankResult(ok=True, score=round(logit * 100, 1),
                            provider="local_bge", model=name)
