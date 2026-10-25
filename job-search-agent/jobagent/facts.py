"""candidate_facts.yaml loader. Values are the source of truth for form fields.

Blank ("") means "unknown". The autofill layer must never guess a blank value; it
fails that application and reports the missing field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import paths

# Fields the autofill layer must have before it may submit an application that
# asks for them. Keyed by a logical name -> dotted path in the facts tree.
CRITICAL_FIELDS = {
    "current_ctc": "compensation.current_ctc",
    "expected_ctc": "compensation.expected_ctc",
    "notice_period_days": "compensation.notice_period_days",
    "total_years": "experience.total_years",
    "current_city": "identity.current_city",
}


def _get(tree: dict[str, Any], dotted: str) -> Any:
    cur: Any = tree
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "") or v == []


@dataclass
class Facts:
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> dict[str, Any]:
        return self.data.get("identity", {}) or {}

    @property
    def compensation(self) -> dict[str, Any]:
        return self.data.get("compensation", {}) or {}

    @property
    def experience(self) -> dict[str, Any]:
        return self.data.get("experience", {}) or {}

    @property
    def application(self) -> dict[str, Any]:
        return self.data.get("application", {}) or {}

    @property
    def screening_answers(self) -> dict[str, Any]:
        return self.data.get("screening_answers", {}) or {}

    def get(self, dotted: str) -> Any:
        return _get(self.data, dotted)

    def missing(self, keys: list[str]) -> list[str]:
        out = []
        for k in keys:
            dotted = CRITICAL_FIELDS.get(k, k)
            if _is_blank(self.get(dotted)):
                out.append(k)
        return out

    def critical_missing(self) -> list[str]:
        return self.missing(list(CRITICAL_FIELDS.keys()))

    def _valued(self, dotted: str) -> tuple[str | None, str | None]:
        val = self.get(dotted)
        if not _is_blank(val):
            return str(val), dotted
        return None, dotted

    def answer_for_question(self, question: str) -> tuple[str | None, str | None]:
        """Map a free-text screening question onto a facts value.

        Returns (value, matched_fact_key) or (None, None). Deterministic first;
        an LLM may be asked only when this returns None (see matcher/autofill).
        """
        q = question.lower()
        # Name splits: LinkedIn often asks first/last separately while facts
        # store a single full_name. Split deterministically, never guess.
        if "first name" in q or "given name" in q:
            full = self.get("identity.full_name")
            if _is_blank(full):
                return None, "identity.full_name"
            return str(full).strip().split()[0], "identity.full_name"
        if "last name" in q or "surname" in q or "family name" in q:
            full = self.get("identity.full_name")
            if _is_blank(full):
                return None, "identity.full_name"
            parts = str(full).strip().split()
            return parts[-1] if parts else None, "identity.full_name"
        if "full name" in q and not any(
            w in q for w in ("company", "university", "college", "school", "employer")
        ):
            return self._valued("identity.full_name")
        if q.strip().rstrip("*").strip() == "name":
            return self._valued("identity.full_name")
        # Recruiter shorthand: a bare "CTC?" means current CTC (expected is
        # always asked explicitly as "expected CTC"), and "NP" means notice
        # period. Word boundaries so "input"-style substrings never match.
        if "expected" not in q and "current" not in q and re.search(r"\bctc\b|\bannual salary\b", q):
            return self._valued("compensation.current_ctc")
        if re.search(r"\bnp\b", q):
            return self._valued("compensation.notice_period_days")
        # Experience scope matters: bare "how many years of experience" is
        # total years, but "how many years of X experience" (Python, healthcare,
        # …) must NEVER silently inherit it — that would fabricate domain
        # tenure. Only exact generic phrasings map; the rest stay unmapped.
        if re.search(r"how many years of (?:work\s+)?experience\b", q):
            return self._valued("experience.total_years")
        # "hands-on / overall / total experience" is still total tenure.
        # Domain qualifiers (healthcare, python, ...) must NEVER match here —
        # that fabrication path stays closed.
        if re.search(r"how many years of (?:work|hands-on|hands on|overall|total)\s+experience\b", q):
            return self._valued("experience.total_years")
        if "relevant experience" in q:
            return self._valued("experience.relevant_years")
        rules: list[tuple[tuple[str, ...], str]] = [
            # Specific before generic: "phone country code" must not resolve
            # to the phone digits.
            (("phone country code", "country code", "dialing code", "country dial"),
             "identity.phone_country_code"),
            (("email address", "email id", "e-mail"), "identity.email"),
            (("linkedin",), "identity.linkedin_url"),
            (("phone number", "mobile number", "contact number", "phone"), "identity.phone"),
            (("current ctc", "current salary", "present ctc", "current compensation"), "compensation.current_ctc"),
            (("expected ctc", "expected salary", "expected annual", "salary expectation", "expected compensation"), "compensation.expected_ctc"),
            (("notice period", "notice", "joining", "able to join",
              "days to join", "joining date", "date of joining"),
             "compensation.notice_period_days"),
            (("last working day", "lwd"), "compensation.last_working_day"),
            (("total experience", "total years", "overall experience"), "experience.total_years"),
            (("current city", "current location", "present location"), "identity.current_city"),
            (("relocat",), "identity.willing_to_relocate"),
            (("work authorization", "eligible to work", "authorized to work"), "experience.work_authorization_india"),
            (("passport",), "experience.passport"),
            (("date of birth", "dob"), "application.date_of_birth"),
            (("gender",), "application.gender"),
            (("nationality",), "application.nationality"),
            (("marital",), "application.marital_status"),
            (("night shift",), "screening_answers.comfortable_with_night_shifts"),
            (("bond",), "screening_answers.comfortable_with_bond"),
            (("onsite", "on-site", "work from office", "working from office"),
             "screening_answers.comfortable_with_onsite"),
            (("commut",), "screening_answers.comfortable_with_commute"),
            (("reason for", "why are you looking", "why do you want to change"), "screening_answers.reason_for_job_change"),
            (("why this company", "why do you want to join"), "screening_answers.why_this_company"),
        ]
        for keywords, key in rules:
            if any(kw in q for kw in keywords):
                val = self.get(key)
                if not _is_blank(val):
                    return str(val), key
                return None, key
        # direct recurring-answer lookup
        for k, v in self.screening_answers.items():
            if k.replace("_", " ") in q and not _is_blank(v):
                return str(v), f"screening_answers.{k}"
        return None, None


def load_facts(path: Path | None = None) -> Facts:
    path = path or paths.FACTS_PATH
    if not path.exists():
        return Facts(data={})
    return Facts(data=yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def write_template(path: Path | None = None, template: Path | None = None) -> Path:
    """Create candidate_facts.yaml from the committed template if missing."""
    path = path or paths.FACTS_PATH
    template = template or (paths.PROJECT_ROOT / "templates" / "candidate_facts.yaml")
    if not path.exists() and template.exists():
        path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return path