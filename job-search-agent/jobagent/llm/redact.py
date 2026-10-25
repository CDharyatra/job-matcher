"""PII redaction before any cloud inference. Enforced by policy + tests.

Never send to a hosted model: name, email, phone, address, links, employer names,
CTC/notice numbers, PAN/Aadhaar, passwords. Send only skills, titles, date ranges,
and de-identified bullets.
"""

from __future__ import annotations

import re

from ..facts import Facts

# Patterns that must always be stripped.
_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?:\+?\d[\d\s\-().]{7,}\d)"), "[PHONE]"),
    (re.compile(r"https?://\S+"), "[URL]"),
    (re.compile(r"\bwww\.\S+"), "[URL]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[ID]"),          # PAN-like
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[ID]"),        # Aadhaar-like
    (re.compile(r"\b\d{1,3}\s?(?:lpa|lakhs?|lacs?)\b", re.IGNORECASE), "[COMP]"),
]


def _replace_literals(text: str, literals: list[str]) -> str:
    for lit in literals:
        if lit and len(lit) >= 2:
            text = re.sub(re.escape(lit), "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def build_redactor(facts: Facts) -> "Redactor":
    ident = facts.identity
    comp = facts.compensation
    literals = [
        str(ident.get("full_name") or ""),
        str(ident.get("full_name_on_id") or ""),
        str(ident.get("email") or ""),
        str(ident.get("phone") or ""),
        str(ident.get("alternate_phone") or ""),
        str(ident.get("current_company") or ""),
        str(comp.get("current_company") or ""),
    ]
    # split names into tokens too
    name_tokens: list[str] = []
    for n in (ident.get("full_name"), ident.get("full_name_on_id")):
        if n:
            name_tokens += [t for t in str(n).split() if len(t) > 2]
    return Redactor(literals + name_tokens)


class Redactor:
    def __init__(self, literals: list[str] | None = None):
        self.literals = literals or []

    def redact(self, text: str) -> str:
        if not text:
            return text
        out = text
        for pat, repl in _PATTERNS:
            out = pat.sub(repl, out)
        out = _replace_literals(out, self.literals)
        return out

    def redact_job(self, job_text: str) -> str:
        return self.redact(job_text)