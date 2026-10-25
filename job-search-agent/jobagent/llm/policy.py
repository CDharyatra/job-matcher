"""The $0 enforcement policy. A paid model id here is a hard error, not a warning."""

from __future__ import annotations

from .paid_blocklist import PAID_MODELS, PAID_PROVIDERS

FREE_PROVIDERS = {"nvidia", "opencode_zen", "openrouter_free", "groq_free",
                  # Mistral Studio free mode: no card, OpenAI-compatible.
                  "mistral_free", "deterministic",
                  # Rerank providers: Jina (10M free tokens), Voyage (200M one-time),
                  # Cohere trial (1k calls/month), local_bge (no network at all).
                  "jina", "voyage", "cohere", "local_bge"}

# Zen ids that are priced Free and therefore allowed.
ZEN_FREE_IDS = {
    "big-pickle", "space-bunny-free", "longcat-2.5-preview-free",
    "mimo-v2.6-flash-free", "mimo-v2.5-free", "ling-3.0-flash-fin-free",
    "nemotron-3-ultra-free", "nemotron-3.5-lightning-free",
    "muse-spark-1.3-contributor-free", "jev-1.13-free",
}

# Zen free models whose terms let the provider train on inputs -> not for PII.
ZEN_TRAINS_ON_INPUT = {
    "big-pickle", "mimo-v2.6-flash-free", "mimo-v2.5-free",
    "ling-3.0-flash-fin-free", "nemotron-3-ultra-free",
    "nemotron-3.5-lightning-free", "muse-spark-1.3-contributor-free",
}


class PaidModelError(ValueError):
    """Raised when a configuration tries to use a banned, paid model."""


def assert_free(provider: str, model: str) -> None:
    if provider in PAID_PROVIDERS:
        raise PaidModelError(f"provider '{provider}' is paid and banned")
    if provider not in FREE_PROVIDERS:
        raise PaidModelError(f"unknown provider '{provider}' (not on the $0 allowlist)")
    if model in PAID_MODELS:
        raise PaidModelError(f"model '{model}' is paid and banned")
    if provider == "opencode_zen" and model not in ZEN_FREE_IDS:
        raise PaidModelError(f"zen model '{model}' is not in the Free allowlist")


def is_pii_safe(provider: str, model: str) -> bool:
    """True only for endpoints that do not train on inputs.

    NVIDIA trial trains/logs; Zen contributor/model-improvement ids train; the
    zero-retention Zen ids and OpenRouter/Groq-free do not.
    """
    if provider == "nvidia":
        return False  # trial ToS: logs + improves products
    if provider == "opencode_zen":
        return model not in ZEN_TRAINS_ON_INPUT
    if provider in {"openrouter_free", "groq_free", "deterministic"}:
        return True
    return False