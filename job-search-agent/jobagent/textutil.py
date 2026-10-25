"""Text, salary, and date utilities. Pure functions, fully testable, no LLM."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

_WS = re.compile(r"\s+")

SENIORITY_WORDS = {
    "senior", "sr", "sr.", "junior", "jr", "jr.", "lead", "staff", "principal",
    "intern", "internship", "trainee", "associate", "architect", "manager",
}

TITLE_SYNONYMS: dict[str, list[str]] = {
    "backend": ["back end", "back-end", "server side", "server-side", "api developer", "backend engineer"],
    "frontend": ["front end", "front-end", "ui developer", "ui engineer", "react developer"],
    "fullstack": ["full stack", "full-stack", "fullstack engineer"],
    "software engineer": ["sde", "software developer", "swe", "programmer", "application developer"],
    "data engineer": ["data platform engineer", "etl developer", "big data engineer"],
    "devops": ["sre", "site reliability", "platform engineer", "infrastructure engineer"],
}

SKILL_ALIASES: dict[str, list[str]] = {
    "postgresql": ["postgres", "psql", "pg"],
    "javascript": ["js", "es6", "ecmascript"],
    "typescript": ["ts"],
    "kubernetes": ["k8s", "kube"],
    "docker": ["containerization", "containers"],
    "aws": ["amazon web services", "ec2", "s3", "lambda"],
    "gcp": ["google cloud platform", "google cloud"],
    "azure": ["microsoft azure"],
    "python": ["py", "python3"],
    "node.js": ["node", "nodejs", "node js"],
    "ci/cd": ["cicd", "ci cd", "continuous integration"],
    "machine learning": ["ml", "deep learning", "dl"],
    "rest api": ["restful", "rest apis", "http api", "rest"],
    "microservices": ["micro services", "micro-services"],
    "rag": ["retrieval-augmented generation", "retrieval augmented generation"],
    "bedrock": ["aws bedrock", "amazon bedrock"],
    "opensearch": ["amazon opensearch"],
    "redis": ["valkey", "redis/valkey"],
    "openai": ["gpt-4", "gpt"],
    "llm": ["large language model", "large language models"],
}


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\u00a0", " ")).strip()


def norm_title(title: str) -> str:
    t = normalize_ws(title).lower()
    t = re.sub(r"\([^)]*\)", " ", t)
    return normalize_ws(t)


def title_tokens(title: str) -> set[str]:
    t = norm_title(title)
    return {w for w in re.split(r"[^a-z0-9+#.]+", t) if w}


CITY_ALIASES = {
    "bangalore": "bengaluru",
    "bengaluru": "bengaluru",
    "gurgaon": "gurugram",
    "gurugram": "gurugram",
    "bombay": "mumbai",
    "mumbai": "mumbai",
    "new delhi": "ncr",
    "delhi": "ncr",
    "ncr": "ncr",
    "noida": "ncr",
}


def canonical_city(name: str) -> str:
    """Map spelling variants (Bangalore/Bengaluru) to one canonical form."""
    key = normalize_ws(name or "").lower()
    return CITY_ALIASES.get(key, key)


def expand_title(title: str) -> list[str]:
    """Return synonyms/variants for a title, for query building."""
    base = norm_title(title)
    out = {base}
    toks = title_tokens(base)
    for key, syns in TITLE_SYNONYMS.items():
        key_toks = set(key.split())
        if key_toks <= toks or key in base:
            for s in syns:
                out.add(s)
    for noise in SENIORITY_WORDS:
        out.add(normalize_ws(re.sub(rf"\b{re.escape(noise)}\b", " ", base)))
    return [x for x in out if x]


def canonical_skill(skill: str) -> str:
    s = normalize_ws(skill).lower()
    for canon, aliases in SKILL_ALIASES.items():
        if s == canon or s in aliases:
            return canon
    return s


def skill_present(skill: str, text: str) -> bool:
    """Word-boundary aware presence check including aliases and plurals.

    Resumes write "WebSockets" / "REST APIs" while vocabularies list the
    singular; both directions are tried (plural formed by +s only, never by
    stripping, so "aws" can never degrade into "aw").
    """
    canon = canonical_skill(skill)
    cands = {canon, *SKILL_ALIASES.get(canon, [])}
    cands |= {c + "s" for c in cands if len(c) > 2}
    low = text.lower()
    for cand in cands:
        pattern = r"(?<![a-z0-9])" + re.escape(cand) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            return True
    return False


# --------------------------------------------------------------------------
# Salary parsing (LPA, CTC, USD, "not disclosed")
# --------------------------------------------------------------------------

_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_CURRENCY = {
    "\u20b9": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "lpa": "INR",
    "$": "USD", "usd": "USD", "\u20ac": "EUR", "eur": "EUR", "\u00a3": "GBP",
}


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def parse_salary(raw: str) -> tuple[float | None, float | None, str]:
    """Return (min, max, currency) in absolute annual currency units.

    18-24 LPA  -> (1800000, 2400000, INR)
    $120,000   -> (120000, 120000, USD)
    Not disclosed -> (None, None, "")
    """
    if not raw:
        return None, None, ""
    text = normalize_ws(raw)
    low = text.lower()
    if any(k in low for k in ("not disclosed", "undisclosed", "hidden", "n/a", "na")):
        return None, None, ""

    # crude currency detection
    currency = ""
    for token, cur in _CURRENCY.items():
        if token in low:
            currency = cur
            break

    # LPA form: 18-24 LPA / 18.5 LPA
    lpa = re.search(rf"{_NUM}\s*(?:-|to)\s*{_NUM}\s*(?:lpa|lacs?|lakhs?)", low)
    if lpa:
        lo = _to_float(lpa.group(1)) * 100000
        hi = _to_float(lpa.group(2)) * 100000
        return lo, hi, "INR"
    single_lpa = re.search(rf"{_NUM}\s*(?:lpa|lacs?|lakhs?)", low)
    if single_lpa:
        v = _to_float(single_lpa.group(1)) * 100000
        return v, v, "INR"

    # plain ranges with currency: $120,000 - $150,000
    cur_sym = r"[$\u20b9\u20ac\u00a3]?\s*"
    rng = re.search(rf"{cur_sym}{_NUM}\s*(?:-|\u2013|to)\s*{cur_sym}{_NUM}", text)
    if rng:
        lo = _to_float(rng.group(1))
        hi = _to_float(rng.group(2))
        if currency == "" and hi < 1000:
            currency = "INR"
        return lo, hi, currency

    single = re.search(rf"{_NUM}", text)
    if single:
        v = _to_float(single.group(1))
        if currency == "":
            currency = "USD" if ("$" in text or "usd" in low) else ""
        return v, v, currency

    return None, None, ""


def parse_relative_date(raw: str, now: datetime | None = None) -> str | None:
    """Parse LinkedIn/Naukri relative dates and absolute dates to ISO UTC."""
    if not raw:
        return None
    now = now or datetime.now(timezone.utc)
    text = normalize_ws(raw).lower()
    text = re.sub(r"^(reposted|posted|published)\s*", "", text)
    text = re.sub(r"\b(on|at)\b.*$", "", text).strip()

    m = re.search(r"(\d+)\s*(minute|min|hour|hr|day|week|month|year)", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        deltas = {
            "minute": timedelta(minutes=n), "min": timedelta(minutes=n),
            "hour": timedelta(hours=n), "hr": timedelta(hours=n),
            "day": timedelta(days=n), "week": timedelta(weeks=n),
            "month": timedelta(days=30 * n), "year": timedelta(days=365 * n),
        }
        return (now - deltas[unit]).isoformat(timespec="seconds")
    if "just now" in text or "today" in text or "few seconds" in text:
        return now.isoformat(timespec="seconds")
    if "yesterday" in text:
        return (now - timedelta(days=1)).isoformat(timespec="seconds")

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def text_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()


def parse_years(text: str) -> tuple[float | None, float | None]:
    """Extract an experience band: '3-6 years', '5+ years', '8-12 Yrs'."""
    if not text:
        return None, None
    low = normalize_ws(text).lower()
    yr = r"(?:years?|yrs?)"
    rng = re.search(rf"(\d{{1,2}})\s*(?:-|to)\s*(\d{{1,2}})\s*(?:\+)?\s*{yr}", low)
    if rng:
        return float(rng.group(1)), float(rng.group(2))
    plus = re.search(rf"(\d{{1,2}})\s*\+\s*{yr}", low)
    if plus:
        return float(plus.group(1)), None
    atleast = re.search(rf"(?:at least|minimum|min)\s*(\d{{1,2}})\s*{yr}", low)
    if atleast:
        return float(atleast.group(1)), None
    single = re.search(rf"(\d{{1,2}})\s*{yr}", low)
    if single:
        v = float(single.group(1))
        return v, v
    return None, None