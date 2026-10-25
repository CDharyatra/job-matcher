"""Names/prices that must never appear in a runnable config or a model call.

Kept as data so the doctor command and tests can import it. This is a defence in
depth: policy.assert_free already refuses anything not on the allowlist.
"""

from __future__ import annotations

# Providers that bill. None of these may be configured.
PAID_PROVIDERS = {
    "anthropic", "openai", "google", "google_ai", "xai", "groq",
    "openrouter", "together", "fireworks", "deepseek_billed", "moonshot_billed",
    "zhipu_billed",
}

# Specific model ids known to be paid (Zen catalog + frontier names).
PAID_MODELS = {
    # OpenCode Zen paid ids (must never be used)
    "muse-spark-1.3", "muse-spark-1.2", "claude-fable-5-1", "claude-fable-5",
    "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
    "claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-5", "claude-sonnet-4-6",
    "claude-sonnet-4-5", "claude-haiku-4-5",
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
    "gemini-3.5-flash-lite", "gemini-3.1-pro", "gemini-3-flash",
    "grok-4.7", "grok-4.6", "grok-4.5", "grok-build-0.1",
    "deepseek-v4.1-flash", "deepseek-v4-pro", "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp", "minimax-m3", "minimax-m2.7", "minimax-m2.5",
    "glm-5.3-flash", "glm-5.3", "glm-5.2", "glm-5.1", "glm-5",
    "kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "kimi-k2.5",
    "qwen3.8-max", "qwen3.8-flash", "qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus",
    "qwen3.5-plus", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol",
    "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.5-pro", "gpt-5.4",
    "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.3-codex",
    "gpt-5.3-codex-spark", "gpt-5.2", "gpt-5.2-codex", "gpt-5.1", "gpt-5.1-codex",
    "gpt-5.1-codex-max", "gpt-5.1-codex-mini", "gpt-5", "gpt-5-codex",
    "gpt-5-nano", "jev-1.13",
}

# NOTE: NVIDIA ids like "deepseek-ai/deepseek-v4.1-flash" are intentionally NOT in
# PAID_MODELS: the SAME weights served on NVIDIA's free trial endpoint are allowed,
# while the billed Zen id "deepseek-v4.1-flash" is banned. The provider check is
# what distinguishes them.
PAID_SERVICE_NAMES = [
    "sendgrid", "mailgun", "postmark", "resend", "amazon ses", "aws ses",
    "linked helper", "linkedhelper", "resumly", "easy apply bot",
    "bright data", "scraperapi", "scrapingbee", "2captcha", "anticaptcha",
    "capmonster", "zenrows",
]