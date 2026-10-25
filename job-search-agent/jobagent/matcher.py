"""Hybrid matcher: deterministic score always; LLM judge for survivors only.

Fusion rule: if the LLM disagrees with a hard deterministic cap, the cap wins.
If the free-model output is worse than deterministic, trust deterministic.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .clean import RouteDecision, route
from .config import Config
from .facts import Facts
from .llm.adapter import LLMClient
from .llm.prompts import match_prompt, validate_match
from .logging_setup import get_logger
from .models import Job
from .resume import ResumeProfile
from .scoring import score_deterministic

log = get_logger("jobagent.matcher")


@dataclass
class MatchResult:
    job_id: int
    overall_match: float
    deterministic_score: float
    llm_score: float | None
    decision: RouteDecision
    reasons: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    resume_used: str = ""
    llm_used: bool = False
    rerank_score: float | None = None


# deterministic pre-filter: jobs this low can never reach 70 even with a boost
PREFILTER_FLOOR = 35.0


def build_rerank_pair(profile: ResumeProfile, facts: Facts, cfg: Config,
                      job: Job, titles: list[str] | None = None,
                      skills: list[str] | None = None) -> tuple[str, str]:
    """Short candidate query + truncated job passage, MS MARCO style.

    Cross-encoders expect a short query and a longer passage; relevance is
    P(passage answers query). With a track lens, the query wears that track's
    title/skills so a Python web role meets the Python candidate, not the ML one.
    Track skills are intersected with resume skills as a typo guard.
    """
    from .textutil import canonical_skill
    title_str = (", ".join(titles or []) or ", ".join((profile.titles or [])[:3])
                 or ", ".join(cfg.search.target_titles[:2]))
    if skills:
        owned = {canonical_skill(s) for s in (profile.skills or [])}
        picked = [s for s in skills if canonical_skill(s) in owned]
        skill_str = ", ".join(picked[:25]) if picked else ", ".join((profile.skills or [])[:25])
    else:
        skill_str = ", ".join((profile.skills or [])[:25])
    try:
        years = float(facts.get("experience.total_years") or 0)
    except (TypeError, ValueError):
        years = 0.0
    query = f"{title_str} | skills: {skill_str} | {years:g} years experience"
    passage = (f"{job.title} at {job.company}, {job.location}. "
               f"{job.requirements} {job.description_text}")[:2000]
    return query, passage


def build_reference(profile: ResumeProfile, facts: Facts) -> str:
    """One-line ideal-candidate reference for reference-based judging."""
    titles = ", ".join((profile.titles or [])[:2])
    skills = ", ".join((profile.skills or [])[:12])
    years = facts.get("experience.total_years") or "unknown"
    return f"{titles}; key skills: {skills}; {years} years experience"


def _run_judge(llm, prompt: str, chain, job: Job, det) -> tuple:
    """One validated judge call. Returns (score|None, used, evidence, note)."""
    t0 = time.monotonic()
    res = llm.complete_json(prompt, chain=chain)
    dt = time.monotonic() - t0
    if res.ok:
        try:
            obj = json.loads(res.text)
        except json.JSONDecodeError:
            obj = {}
        ok, why = validate_match(obj) if obj else (False, "invalid json")
        if ok:
            score = float(obj["overall_match"])
            log.info("judge %s score=%s det=%s cached=%s %.1fs | %s",
                     res.model, score, det.score, res.cached, dt,
                     (job.title or "?")[:70])
            return score, True, obj.get("evidence", []), f"llm judge ({res.model}): {score}"
        log.warning("judge %s rejected (%s) %.1fs | %s",
                    res.model, why, dt, (job.title or "?")[:70])
        return None, False, [], f"llm output rejected: {why}"
    log.warning("judge unavailable (%s) %.1fs | %s - deterministic only",
                res.error, dt, (job.title or "?")[:70])
    return None, False, [], "llm unavailable"


def _judge_prompt(job: Job, facts: Facts, cfg: Config,
                  profile: ResumeProfile, nice: list[str] | None = None) -> str:
    return match_prompt(
        job.title, job.description_text, profile.deidentified_blob(),
        cfg.search.must_have_skills,
        nice if nice is not None else cfg.search.nice_to_have_skills,
        job.experience_min or "", job.experience_max or "",
        reference=build_reference(profile, facts),
    )


def match_job(job: Job, job_id: int, facts: Facts, cfg: Config, profile: ResumeProfile,
              llm: LLMClient | None = None, use_llm: bool = True,
              rerank=None) -> MatchResult:
    det = score_deterministic(job, facts, cfg)
    reasons = list(det.reasons)
    evidence = list(det.evidence)

    llm_score: float | None = None
    llm_used = False
    rerank_score: float | None = None
    thin = len(job.description_text or "") < 100

    # Cross-encoder relevance first, once per track: a Python web role meets
    # the Python-track query, an ML role the ML-track query. Joint attention
    # beats keyword overlap and costs one fast forward pass. Skipped under a
    # hard cap (cap decides anyway).
    from .scoring import track_specs
    specs = track_specs(cfg)
    nice_by_track = {name: nice for name, _titles, nice in specs}
    judge_nice = nice_by_track.get(det.track, cfg.search.nice_to_have_skills)
    if rerank is not None and cfg.rerank.enabled and not det.hard_cap:
        best_rr = None
        for name, titles, nice in specs:
            query, passage = build_rerank_pair(profile, facts, cfg, job, titles, nice)
            rr = rerank.score(query, passage, chain=cfg.rerank.chain)
            if rr.ok and rr.score is not None and (
                    best_rr is None or float(rr.score) > best_rr[0]):
                best_rr = (float(rr.score), name, rr)
        if best_rr is not None:
            rerank_score, rr_track, rr = best_rr
            judge_nice = nice_by_track.get(rr_track, judge_nice)
            reasons.append(f"rerank ({rr.provider}/{rr.model}/{rr_track or 'base'}): "
                           f"{rerank_score}")
            log.info("rerank %s/%s score=%s | %s", rr.provider, rr.model,
                     rerank_score, (job.title or "?")[:70])
        else:
            reasons.append("rerank unavailable")

    if rerank_score is None:
        return _match_legacy(job, job_id, facts, cfg, profile, det, reasons,
                             evidence, llm, use_llm, thin, judge_nice)

    prelim = round(0.55 * rerank_score + 0.45 * det.score, 1)
    reasons.append(f"preliminary (rerank+det): {prelim}")
    lo, hi = cfg.rerank.borderline_lo, cfg.rerank.borderline_hi
    if use_llm and llm is not None and not thin and lo <= prelim <= hi:
        llm_score, llm_used, ev, note = _run_judge(
            llm, _judge_prompt(job, facts, cfg, profile, judge_nice),
            cfg.llm.judge_chain, job, det)
        reasons.append(note)
        evidence += ev
    else:
        reasons.append("outside judge band; rerank+deterministic only")
        log.debug("judge skipped (prelim=%s) | %s", prelim, (job.title or "?")[:70])

    if llm_score is None:
        overall = prelim
    else:
        overall = round(0.5 * llm_score + 0.3 * rerank_score + 0.2 * det.score, 1)
        if llm_score > prelim + 30:
            overall = min(overall, prelim + 20)
            reasons.append("llm over-optimism tempered")
        if llm_score < prelim - 15:
            overall = min(overall, llm_score + 5)
            reasons.append("det over-optimism corrected by judge")

    overall = round(min(100.0, max(0.0, overall)), 1)
    decision = route(job, overall, facts, cfg)
    return MatchResult(
        job_id=job_id, overall_match=overall, deterministic_score=det.score,
        llm_score=llm_score, decision=decision, reasons=reasons, evidence=evidence,
        resume_used="default", llm_used=llm_used, rerank_score=rerank_score,
    )


def _match_legacy(job: Job, job_id: int, facts: Facts, cfg: Config,
                  profile: ResumeProfile, det, reasons: list, evidence: list,
                  llm, use_llm: bool, thin: bool,
                  judge_nice: list[str] | None = None) -> MatchResult:
    """Pre-rerank path, preserved bit-for-bit for fallback when no reranker."""
    llm_score: float | None = None
    llm_used = False

    # Cheap pass: skip obvious misses so free-model budget is spent on hard cases.
    # Jobs without an enriched description (beyond the detail cap) are scored
    # deterministic-only: the judge needs real job text, not a bare title.
    spend_llm = (
        use_llm
        and llm is not None
        and not det.hard_cap
        and det.score >= PREFILTER_FLOOR
        and not thin
    )
    if not spend_llm:
        log.debug("judge skipped (det=%s%s%s) | %s", det.score,
                  ", hard-cap" if det.hard_cap else "",
                  ", thin-desc" if thin else "",
                  (job.title or "?")[:70])

    if spend_llm:
        llm_score, llm_used, ev, note = _run_judge(
            llm, _judge_prompt(job, facts, cfg, profile, judge_nice),
            cfg.llm.judge_chain, job, det)
        reasons.append(note)
        evidence += ev

    # fusion
    if det.hard_cap:
        overall = min(det.score, llm_score if llm_score is not None else det.score)
        reasons.append("hard cap enforced")
    elif llm_score is None:
        overall = det.score
    else:
        overall = round((det.score * 0.35) + (llm_score * 0.65), 1)
        # if free model rates clearly higher than evidence supports, temper it
        if llm_score > det.score + 30:
            overall = min(overall, det.score + 20)
            reasons.append("llm over-optimism tempered")
        # if the judge rates materially lower, trust the judge downward: the LLM
        # exists precisely to catch over-optimistic keyword overlap
        if llm_score < det.score - 15:
            overall = min(overall, llm_score + 5)
            reasons.append("det over-optimism corrected by judge")

    overall = round(min(100.0, max(0.0, overall)), 1)
    decision = route(job, overall, facts, cfg)
    resume_used = "default"

    return MatchResult(
        job_id=job_id, overall_match=overall, deterministic_score=det.score,
        llm_score=llm_score, decision=decision, reasons=reasons, evidence=evidence,
        resume_used=resume_used, llm_used=llm_used,
    )