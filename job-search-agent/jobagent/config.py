"""Typed configuration loading from config.yaml + .env with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import paths


def load_env(path: Path | None = None) -> dict[str, str]:
    """Minimal .env reader. Does not overwrite real environment variables."""
    path = path or paths.ENV_PATH
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def get_secret(key: str, env: dict[str, str] | None = None) -> str:
    env = env if env is not None else load_env()
    return os.environ.get(key) or env.get(key, "")


@dataclass
class SearchConfig:
    target_titles: list[str] = field(default_factory=list)
    must_have_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    experience_min: Any = ""
    experience_max: Any = ""
    locations: list[str] = field(default_factory=list)
    # Per-title skill lenses: [{title: str, skills: [str]}]. Each job is scored
    # against every track and keeps its best. All skills must exist on the
    # resume — tracks describe the candidate, never invent requirements.
    tracks: list[dict] = field(default_factory=list)
    remote_ok: bool = True
    date_posted_ladder_hours: list[int] = field(default_factory=lambda: [24, 48, 168])
    max_pages_per_query: int = 3
    max_details_per_run: int = 50
    daily_collection_cap_per_platform: int = 200
    min_results_before_widening: int = 15


@dataclass
class RoutingConfig:
    discard_below: float = 70.0
    inbox_above: float = 90.0
    # Minimum acceptable pay in LPA. Jobs with DISCLOSED pay topping below
    # this are discarded; undisclosed pay (or non-INR, which can't be
    # compared) always passes to human review.
    min_pay_lpa: float = 0.0


@dataclass
class ApplyConfig:
    daily_auto_apply_cap_per_platform: int = 10
    min_seconds_between_applies: int = 90
    min_seconds_between_actions: int = 4
    quiet_hours: dict[str, str] = field(default_factory=lambda: {"start": "22:30", "end": "08:00"})
    live_submit_enabled: bool = False
    precision_gate: float = 0.80


@dataclass
class EmailConfig:
    digest_enabled: bool = True
    send_daily_summary_even_if_zero: bool = True
    max_packet_emails_per_run: int = 25
    # Job-alert email intake. OFF by default: the user wants scoring to run on
    # web-collected jobs only. Enable only as a fallback if live collection is
    # ever blocked for days.
    alert_intake_enabled: bool = False


@dataclass
class BrowserConfig:
    chrome_path: str = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
    user_data_dir: str = "./.browser/profile"
    remote_debugging_port: int = 9222
    headless: bool = False
    attach_mode: str = "cdp"
    slow_mo_ms: int = 50
    navigation_timeout_ms: int = 45000


@dataclass
class LLMModel:
    provider: str
    model: str


@dataclass
class LLMConfig:
    enabled: bool = True
    daily_call_budget_per_model: int = 300
    max_retries: int = 2
    backoff_base_seconds: int = 2
    request_timeout_seconds: int = 60
    prompt_version: str = "v1"
    # Minimum seconds between calls per provider (TPM protection: Groq free
    # allows ~8K tokens/min, and one judge prompt eats most of it).
    provider_min_interval_seconds: dict[str, float] = field(default_factory=dict)
    judge_chain: list[LLMModel] = field(default_factory=list)
    classify_chain: list[LLMModel] = field(default_factory=list)
    long_context_chain: list[LLMModel] = field(default_factory=list)


@dataclass
class RerankConfig:
    enabled: bool = True
    daily_budget_per_model: int = 1000
    # The LLM judge only runs inside this preliminary-score band, where human
    # judgment is genuinely ambiguous. Outside it, rerank+deterministic decide.
    borderline_lo: float = 60.0
    borderline_hi: float = 93.0
    chain: list[LLMModel] = field(default_factory=list)


@dataclass
class StorageConfig:
    sqlite_path: str = "./data/jobagent.sqlite3"
    cache_dir: str = "./data/cache"
    log_dir: str = "./data/logs"


@dataclass
class Config:
    search: SearchConfig = field(default_factory=SearchConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    apply: ApplyConfig = field(default_factory=ApplyConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    rerank: RerankConfig = field(default_factory=RerankConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    platforms: dict[str, Any] = field(default_factory=dict)
    blocklist: dict[str, list[str]] = field(default_factory=dict)
    scheduler: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _chain(raw: list[dict[str, Any]] | None) -> list[LLMModel]:
    return [LLMModel(provider=m["provider"], model=m["model"]) for m in (raw or [])]


def load_config(path: Path | None = None) -> Config:
    path = path or paths.CONFIG_PATH
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        enabled=llm_raw.get("enabled", True),
        daily_call_budget_per_model=llm_raw.get("daily_call_budget_per_model", 300),
        max_retries=llm_raw.get("max_retries", 2),
        backoff_base_seconds=llm_raw.get("backoff_base_seconds", 2),
        request_timeout_seconds=llm_raw.get("request_timeout_seconds", 60),
        prompt_version=llm_raw.get("prompt_version", "v1"),
        provider_min_interval_seconds=llm_raw.get("provider_min_interval_seconds", {}),
        judge_chain=_chain(llm_raw.get("judge_chain")),
        classify_chain=_chain(llm_raw.get("classify_chain")),
        long_context_chain=_chain(llm_raw.get("long_context_chain")),
    )

    rr_raw = raw.get("rerank", {})
    rerank = RerankConfig(
        enabled=rr_raw.get("enabled", True),
        daily_budget_per_model=rr_raw.get("daily_budget_per_model", 1000),
        borderline_lo=rr_raw.get("borderline_lo", 60.0),
        borderline_hi=rr_raw.get("borderline_hi", 93.0),
        chain=_chain(rr_raw.get("chain")),
    )

    cfg = Config(
        search=SearchConfig(**raw.get("search", {})),
        routing=RoutingConfig(**raw.get("routing", {})),
        apply=ApplyConfig(**raw.get("apply", {})),
        email=EmailConfig(**raw.get("email", {})),
        browser=BrowserConfig(**raw.get("browser", {})),
        llm=llm,
        rerank=rerank,
        storage=StorageConfig(**raw.get("storage", {})),
        platforms=raw.get("platforms", {}),
        blocklist=raw.get("blocklist", {}),
        scheduler=raw.get("scheduler", {}),
        raw=raw,
    )
    # Resolve relative runtime paths against HOME so scheduled runs work no
    # matter what working directory Task Scheduler starts them in.
    base = paths.HOME
    for attr in ("sqlite_path", "cache_dir", "log_dir"):
        val = getattr(cfg.storage, attr)
        if val and not Path(val).is_absolute():
            setattr(cfg.storage, attr, str((base / val).resolve()))
    if cfg.browser.user_data_dir and not Path(cfg.browser.user_data_dir).is_absolute():
        cfg.browser.user_data_dir = str((base / cfg.browser.user_data_dir).resolve())
    return cfg