"""Cleaning and routing logic. Deterministic, testable, no LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config
from .facts import Facts
from .models import Job

BUCKET_DISCARD = "C_discard"
BUCKET_INBOX = "B_inbox"
BUCKET_APPLY = "A_autoapply"


def is_blocklisted(job: Job, cfg: Config) -> tuple[bool, str]:
    companies = [c.lower() for c in (cfg.blocklist.get("companies") or [])]
    keywords = [k.lower() for k in (cfg.blocklist.get("keywords") or [])]
    if any(c and c in job.company.lower() for c in companies):
        return True, "blocklisted company"
    blob = f"{job.title} {job.description_text}".lower()
    for k in keywords:
        # word-boundary match: "intern" must not fire on "internal tools"
        if k and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", blob):
            return True, f"blocklisted keyword: {k}"
    return False, ""


def is_obvious_spam(job: Job) -> tuple[bool, str]:
    blob = f"{job.title} {job.description_text}".lower()
    spam_markers = [
        "registration fee", "pay a fee", "security deposit", "earn from home",
        "100% commission", "unlimited earning", "no experience needed high salary",
    ]
    for m in spam_markers:
        if re.search(r"(?<![a-z0-9])" + re.escape(m) + r"(?![a-z0-9])", blob):
            return True, f"spam marker: {m}"
    if len(job.description_text) < 40 and job.apply_type == "unknown":
        return True, "empty/unknown posting"
    return False, ""


def location_authorization_ok(job: Job, facts: Facts, cfg: Config) -> tuple[bool, str]:
    if not facts.get("experience.work_authorization_india") and not facts.get("experience.work_authorization_other"):
        return True, "authorization not recorded; allow"
    return True, "authorization ok"


def location_in_scope(job: Job, cfg: Config) -> tuple[bool, str]:
    """Bangalore-only gate. Search queries are already location-scoped, but
    multi-city postings (e.g. 'Bengaluru, Hyderabad, Delhi NCR') slip through.
    In-scope when the location is blank (can't judge), names Bangalore
    under either spelling, or is remote."""
    loc = (job.location or "").strip().lower()
    if not loc:
        return True, "location blank; allow"
    if "bengaluru" in loc or "bangalore" in loc or "remote" in loc:
        return True, "location ok"
    return False, f"location outside Bangalore ({job.location[:60]})"


def salary_in_scope(job: Job, cfg: Config) -> tuple[bool, str]:
    """Pay bar: keep undisclosed pay and disclosed pay reaching the bar;
    discard disclosed pay topping below it (e.g. an 8-14 Lacs posting
    against a 19 LPA bar)."""
    try:
        bar_lpa = float(getattr(cfg.routing, "min_pay_lpa", 0) or 0)
    except (TypeError, ValueError):  # noqa: BLE001
        return True, "pay bar unreadable; allow"
    if not bar_lpa:
        return True, "no pay bar configured"
    lo, hi = job.salary_min, job.salary_max
    if lo is None and hi is None:
        return True, "pay undisclosed; allow"
    cur = (job.salary_currency or "").upper()
    if cur and cur != "INR":
        return True, f"non-INR pay ({cur}); allow"
    top = hi if hi is not None else lo
    if top is None:  # pragma: no cover - defensive
        return True, "pay unreadable; allow"
    if top >= bar_lpa * 100000:
        return True, "pay ok"
    return False, f"pay below bar (tops {top / 100000:g} < {bar_lpa:g} LPA)"


@dataclass
class RouteDecision:
    bucket: str
    reason: str
    missing_facts: list[str]


def route(job: Job, overall_match: float, facts: Facts, cfg: Config) -> RouteDecision:
    """Apply the user's exact 70/90 rules."""
    ok, why = location_in_scope(job, cfg)
    if not ok:
        return RouteDecision(BUCKET_DISCARD, why, [])
    ok, why = salary_in_scope(job, cfg)
    if not ok:
        return RouteDecision(BUCKET_DISCARD, why, [])
    if overall_match < cfg.routing.discard_below:
        return RouteDecision(BUCKET_DISCARD, f"score {overall_match} < {cfg.routing.discard_below}", [])
    if overall_match > cfg.routing.inbox_above:
        return RouteDecision(BUCKET_INBOX, f"score {overall_match} > {cfg.routing.inbox_above} -> human look", [])
    # 70..90 inclusive
    in_platform = job.apply_type in {"easy_apply", "naukri_apply"}
    if not in_platform:
        return RouteDecision(BUCKET_INBOX, f"external/{job.apply_type} apply -> email", [])
    # In-platform but we do not know which questions a form asks until we open it.
    # The autofill layer re-checks missing facts at submit time.
    return RouteDecision(BUCKET_APPLY, "in-platform apply, score in 70-90 band", [])