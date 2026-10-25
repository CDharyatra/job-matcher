"""Prompt builders + JSON schema validation. Every routing-affecting call returns
validated JSON. Invalid or evidence-less output is retried, then failed over.
"""

from __future__ import annotations

import json
from typing import Any

MATCH_SCHEMA = {
    "overall_match": "number 0-100",
    "must_have_hits": "list[str]",
    "must_have_misses": "list[str]",
    "evidence": "list[{requirement:str, resume_signal:str, match:bool}]",
    "resume_version_suggestion": "str",
    "rationale": "str (<= 400 chars)",
}


def match_prompt(job_title: str, job_text: str, deidentified_resume: str,
                 must_have: list[str], nice_to_have: list[str],
                 experience_min: Any = "", experience_max: Any = "",
                 reference: str = "") -> str:
    """Job text is already PII-redacted by the adapter before send."""
    return f"""You are a strict technical recruiter. Decide whether the candidate can
credibly DO this job as written. "Could learn it" is NOT a match. Never invent skills
the candidate does not list.

Return ONLY a JSON object with keys: {json.dumps(MATCH_SCHEMA)}

Rules:
- overall_match is 0-100. A 70 means the candidate could credibly do the job.
- The 90+ band should be RARE. If you would give many jobs >90, lower them.
- must_have_misses must each reduce the score and, if any is missing, the score must be <=55.
- evidence must map specific job requirements to specific candidate bullets/skills.
  If you cannot cite evidence, the match is false.
- Only use skills actually present in the candidate summary below.

CANDIDATE (de-identified):
{deidentified_resume}

REFERENCE IDEAL PROFILE (score against this too; it anchors your scale):
{reference}

MUST-HAVE SKILLS: {', '.join(must_have)}
NICE-TO-HAVE: {', '.join(nice_to_have)}
JOB EXPERIENCE BAND: {experience_min} - {experience_max}

JOB TITLE: {job_title}
JOB DESCRIPTION:
{job_text[:6000]}
JSON:"""


def validate_match(obj: dict[str, Any]) -> tuple[bool, str]:
    try:
        score = float(obj.get("overall_match"))
    except (TypeError, ValueError):
        return False, "overall_match missing/not a number"
    if not (0 <= score <= 100):
        return False, "overall_match out of range"
    ev = obj.get("evidence")
    if not isinstance(ev, list) or not ev:
        return False, "evidence must be a non-empty list"
    for item in ev:
        if not isinstance(item, dict) or "requirement" not in item:
            return False, "evidence item malformed"
    misses = obj.get("must_have_misses")
    if isinstance(misses, list) and misses and score > 55:
        return False, "must-have miss but score > 55 (violates rule)"
    return True, ""


def screening_prompt(question: str, known_facts: dict[str, str]) -> str:
    return f"""Map a job-application screening question to a stored candidate fact.
Return ONLY JSON: {{"fact_key": "string or empty", "value": "string or empty"}}.
Do NOT invent a value. If the question needs a fact not listed, return empty strings.

KNOWN FACTS:
{json.dumps(known_facts, ensure_ascii=False, indent=2)}

QUESTION: {question}
JSON:"""