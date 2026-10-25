"""Deterministic 0-100 scorer. Runs before any LLM call; always available.

Design goals from the brief:
  - must-have miss hard-caps below the discard threshold;
  - title synonyms handled;
  - years as ranges;
  - location / remote;
  - recency;
  - salary vs expected-CTC floor;
  - never invent a skill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Config
from .facts import Facts
from .models import Job
from .textutil import (canonical_city, canonical_skill, skill_present, title_tokens,
                       TITLE_SYNONYMS)

WEIGHTS = {
    "title": 25.0,
    "must_have": 35.0,
    "nice_to_have": 10.0,
    "years": 12.0,
    "location": 8.0,
    "recency": 5.0,
    "salary": 5.0,
}


@dataclass
class DeterministicResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    hard_cap: bool = False
    must_miss: list[str] = field(default_factory=list)
    track: str = ""


def _title_similarity(job_title: str, target_titles: list[str]) -> tuple[float, str]:
    jt = title_tokens(job_title)
    best = 0.0
    matched = ""
    for target in target_titles or []:
        tt = title_tokens(target)
        if not tt and not jt:
            continue
        overlap = len(jt & tt) / max(1, len(tt | jt))
        # synonym boost
        for key, syns in TITLE_SYNONYMS.items():
            if key in target.lower() and any(s in job_title.lower() for s in syns):
                overlap = max(overlap, 0.75)
        if overlap > best:
            best, matched = overlap, target
    return best, matched


def _years_fit(job: Job, facts: Facts) -> tuple[float, str]:
    jmin, jmax = job.experience_min, job.experience_max
    try:
        user_years = float(facts.get("experience.total_years") or facts.get("experience.relevant_years") or 0)
    except (TypeError, ValueError):
        user_years = 0.0
    if jmin is None and jmax is None:
        return 0.6, "experience band not stated in posting"
    if user_years == 0:
        return 0.5, "user years unknown; neutral"
    lo = jmin if jmin is not None else 0
    hi = jmax if jmax is not None else 99
    if lo <= user_years <= hi:
        return 1.0, f"years fit ({user_years:g} within {lo:g}-{hi:g})"
    if user_years < lo:
        gap = lo - user_years
        return max(0.0, 1.0 - gap / 5.0), f"under by {gap:g} years"
    gap = user_years - hi
    return max(0.0, 1.0 - gap / 8.0), f"over by {gap:g} years"


def _location_fit(job: Job, facts: Facts, cfg: Config) -> tuple[float, str]:
    if job.remote_type == "remote" and cfg.search.remote_ok:
        return 1.0, "remote role"
    loc = (job.location or "").lower()
    user_city = str(facts.get("identity.current_city") or "")
    reloc = [str(c) for c in (facts.get("identity.relocate_cities") or [])]
    targets = {canonical_city(t) for t in (cfg.search.locations or [])}
    targets |= {canonical_city(user_city)} | {canonical_city(c) for c in reloc}
    targets.discard("")
    if not loc:
        return 0.6, "job location blank"
    # Compare per city-part so "Bangalore, Karnataka" matches "Bengaluru".
    for part in re.split(r"[,/]", loc):
        if canonical_city(part) in targets:
            return 1.0, f"location match: {part.strip()}"
    for t in targets:
        if t and t in loc:
            return 1.0, f"location match: {t}"
    if cfg.search.remote_ok and "remote" in loc:
        return 1.0, "listed remote"
    return 0.25, "location not in preferred/relocation list"


def _recency_score(job: Job) -> tuple[float, str]:
    age = job.age_hours()
    if age is None:
        return 0.5, "posted date unknown"
    if age <= 24:
        return 1.0, "posted < 24h"
    if age <= 48:
        return 0.85, "posted < 48h"
    if age <= 168:
        return 0.6, "posted < 7d"
    return 0.2, "older than 7d"


def _salary_fit(job: Job, facts: Facts) -> tuple[float, str]:
    floor = facts.get("compensation.expected_ctc_floor") or facts.get("compensation.expected_ctc")
    if job.salary_min is None or floor in (None, ""):
        return 0.6, "salary not disclosed or floor unknown"
    try:
        floor_val = float(floor)
    except (TypeError, ValueError):
        return 0.6, "floor unparseable"
    # normalize floor if in LPA
    if str(facts.get("compensation.expected_ctc_unit") or "LPA").upper() == "LPA":
        floor_val *= 100000
    top = job.salary_max if job.salary_max is not None else job.salary_min
    if top >= floor_val:
        return 1.0, "salary meets floor"
    if job.salary_min >= floor_val * 0.85:
        return 0.7, "salary slightly below floor"
    return 0.2, "salary below floor"


def track_specs(cfg: Config) -> list[tuple[str, list[str], list[str]]]:
    """(track name, titles, nice skills) per target track.

    Must-haves stay global (Python is non-negotiable on both tracks); each track
    contributes its own title + nice-skill lens. Without configured tracks,
    one spec from the legacy target_titles/nice_to_have_skills is used.
    """
    specs = []
    for t in (cfg.search.tracks or []):
        if isinstance(t, dict) and t.get("title"):
            specs.append((t["title"], [t["title"]],
                          t.get("skills") or cfg.search.nice_to_have_skills))
    if not specs:
        specs.append(("", list(cfg.search.target_titles or []),
                      list(cfg.search.nice_to_have_skills or [])))
    return specs


def score_deterministic(job: Job, facts: Facts, cfg: Config) -> DeterministicResult:
    """Score against every track; the job keeps its best track. A Python web
    role is judged as a Python role, not as a failed ML role."""
    best: DeterministicResult | None = None
    for name, titles, nice_skills in track_specs(cfg):
        cand = _score_with(job, facts, cfg,
                           titles or list(cfg.search.target_titles or []),
                           list(cfg.search.must_have_skills or []),
                           nice_skills, track_name=name)
        if best is None or cand.score > best.score:
            best = cand
    assert best is not None
    return best


def _score_with(job: Job, facts: Facts, cfg: Config, titles: list[str],
                must_raw: list[str], nice_raw: list[str],
                track_name: str = "") -> DeterministicResult:
    reasons: list[str] = []
    evidence: list[dict] = []
    blob = f"{job.title}\n{job.description_text}\n{job.requirements}"

    title_sim, title_match = _title_similarity(job.title, titles)
    reasons.append(f"title similarity {title_sim:.2f} vs '{title_match or 'n/a'}'")

    must = [canonical_skill(s) for s in must_raw]
    nice = [canonical_skill(s) for s in nice_raw]
    must_hits = [s for s in must if skill_present(s, blob)]
    must_miss = [s for s in must if s not in must_hits]
    nice_hits = [s for s in nice if skill_present(s, blob)]

    # Must-have over the config list AND any explicitly mandatory phrasing.
    must_cov = len(must_hits) / len(must) if must else 0.6
    nice_cov = len(nice_hits) / len(nice) if nice else 0.5

    for s in must_hits:
        evidence.append({"requirement": f"must-have: {s}", "resume_signal": f"present in posting", "match": True})
    for s in must_miss:
        evidence.append({"requirement": f"must-have: {s}", "resume_signal": "absent from posting", "match": False})

    years_s, years_r = _years_fit(job, facts)
    loc_s, loc_r = _location_fit(job, facts, cfg)
    rec_s, rec_r = _recency_score(job)
    sal_s, sal_r = _salary_fit(job, facts)
    reasons += [years_r, loc_r, rec_r, sal_r]

    score = (
        WEIGHTS["title"] * title_sim
        + WEIGHTS["must_have"] * must_cov
        + WEIGHTS["nice_to_have"] * nice_cov
        + WEIGHTS["years"] * years_s
        + WEIGHTS["location"] * loc_s
        + WEIGHTS["recency"] * rec_s
        + WEIGHTS["salary"] * sal_s
    )

    hard_cap = False
    # Java-only role vs Python-only resume must never auto-apply.
    if must_miss:
        # if any must-have is missing, cap hard below discard threshold
        hard_cap = True
        score = min(score, 55.0)
        reasons.append(f"HARD CAP: missing must-have skills {must_miss}")

    negation_hit = any(
        kw and re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])",
                         blob.lower())
        for kw in (cfg.search.negative_keywords or []))
    if negation_hit:
        hard_cap = True
        score = min(score, 40.0)
        reasons.append("HARD CAP: negative keyword present")

    return DeterministicResult(
        score=round(min(100.0, max(0.0, score)), 1),
        reasons=reasons,
        evidence=evidence,
        hard_cap=hard_cap,
        must_miss=must_miss,
        track=track_name,
    )