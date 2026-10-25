"""Skill-gap analysis: which skills the market demands that the resume lacks.

Runs over jobs that scored near or above the bar (not obvious discards), so the
gaps are skills worth learning, not noise from irrelevant postings. Feeds the
digest's upskill section and nothing else — it never affects routing.
"""

from __future__ import annotations

from collections import Counter

from .logging_setup import get_logger
from .models import Job
from .resume import ResumeProfile, _SKILL_VOCAB
from .textutil import canonical_skill, skill_present

log = get_logger("jobagent.gaps")

# Only jobs at/above this score inform gaps (near-misses and up).
RELEVANCE_FLOOR = 50.0


def skill_gaps(scored: list[tuple[Job, float]], profile: ResumeProfile,
               top_n: int = 10) -> list[dict]:
    """Return [{skill, jobs, example}] for demanded-but-missing skills."""
    owned = {canonical_skill(s) for s in (profile.skills or [])}
    vocab = sorted({canonical_skill(s) for s in _SKILL_VOCAB} - owned)
    counts: Counter = Counter()
    examples: dict[str, str] = {}
    for job, score in scored:
        if score < RELEVANCE_FLOOR:
            continue
        blob = f"{job.title}\n{job.requirements}\n{job.description_text}"
        for skill in vocab:
            if skill_present(skill, blob):
                counts[skill] += 1
                if skill not in examples and job.title:
                    examples[skill] = job.title[:80]
    out = [{"skill": s, "jobs": n, "example": examples.get(s, "")}
           for s, n in counts.most_common(top_n)]
    log.info("skill gaps: %d skills from %d relevant jobs",
             len(out), sum(1 for _, sc in scored if sc >= RELEVANCE_FLOOR))
    return out
