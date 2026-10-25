"""ATS collector: Greenhouse / Lever / Ashby public job-board APIs.

No auth, no browser — plain HTTPS GETs. Boards are curated product companies
(config ``platforms.ats.companies``). Every job maps to the shared Job model
with ``apply_type="external_ats"``, so routing sends qualifying jobs to the
inbox with a direct apply link. ATS jobs are never auto-applied.

Salary note: these APIs do not carry compensation, so the ~20 LPA bar cannot
be filtered here — it stays a human call at inbox review.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timezone

from .logging_setup import get_logger
from .models import Job
from .textutil import normalize_ws, parse_years

log = get_logger("jobagent.ats")

UA = {"User-Agent": "jobagent/1.0 (+local job search)"}

# Verified live 2026-10-13: each board currently lists Bangalore/remote
# ML-or-Python roles. Product companies only — no staffing/consultancies.
DEFAULT_COMPANIES = [
    {"provider": "greenhouse", "board": "rzr", "company": "RZR"},
    {"provider": "greenhouse", "board": "skildai-careers", "company": "Skild AI"},
    {"provider": "greenhouse", "board": "enterpret", "company": "Enterpret"},
    {"provider": "lever", "board": "neuron7", "company": "Neuron7"},
    {"provider": "lever", "board": "levelai", "company": "Level AI"},
    {"provider": "ashby", "board": "spector-ai", "company": "Spector.ai"},
    {"provider": "ashby", "board": "wisdom-ai", "company": "Wisdom AI"},
]

# Light title prefilter — broad enough to keep "Software Engineer, Backend",
# narrow enough to drop sales/recruiting. The scorer discards the rest.
_TITLE_KEEP = (
    "machine learning", "artificial intelligence", " ai ", " ml ",
    "/ai ", "-ai ", "python", "data scient", "data eng", "backend",
    "llm", "gen ai", "genai", " nlp", "nlp ", "pytorch", " rag", "rag ",
)


def _title_relevant(title: str) -> bool:
    padded = f" {(title or '').lower()} "
    return any(k in padded for k in _TITLE_KEEP)


def _normalize_location(title: str, loc: str) -> str:
    """Reported location, plus title-declared Bangalore (some boards report
    only one city of a multi-city posting, e.g. Level AI's Noida)."""
    loc = normalize_ws(loc or "")
    if ("bengaluru" in loc.lower() or "bangalore" in loc.lower()
            or "bengaluru" in (title or "").lower()
            or "bangalore" in (title or "").lower()):
        if "bengaluru" not in loc.lower() and "bangalore" not in loc.lower():
            loc = f"{loc} / Bengaluru" if loc else "Bengaluru"
    return loc


def _in_scope(loc: str) -> bool:
    low = (loc or "").lower()
    return (not low.strip() or "bengaluru" in low or "bangalore" in low
            or "remote" in low)


def _strip_html(raw: str) -> str:
    # Unescape FIRST: Greenhouse ships HTML-escaped content (&lt;p&gt;),
    # which must become real tags before stripping (and entities like
    # &amp; must resolve even in plain text).
    text = html.unescape(raw or "")
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]*>", " ", text)
    return normalize_ws(html.unescape(text))


def _iso(value) -> str | None:
    """Epoch-ms, epoch-s, or ISO string -> ISO UTC. None when unparseable."""
    try:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:  # ms
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):  # noqa: BLE001
        return None


def _get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _greenhouse_jobs(board: str) -> list[dict]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    return data.get("jobs", []) if isinstance(data, dict) else []


def _greenhouse_detail(board: str, job_id) -> str:
    try:
        data = _get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}?content=true")
        return _strip_html(data.get("content", "") if isinstance(data, dict) else "")
    except Exception:  # noqa: BLE001
        return ""


def _lever_jobs(board: str) -> list[dict]:
    data = _get_json(f"https://api.lever.co/v0/postings/{board}")
    return data if isinstance(data, list) else []


def _lever_detail(board: str, posting_id: str) -> str:
    try:
        data = _get_json(f"https://api.lever.co/v0/postings/{board}/{posting_id}")
        if not isinstance(data, dict):
            return ""
        parts = [data.get("description", "")]
        for lst in data.get("lists", []) or []:
            if not isinstance(lst, dict):
                continue
            parts.append(lst.get("text", "") or "")
            content = lst.get("content", [])
            if isinstance(content, str):
                parts.append(content)  # some boards inline HTML as a string
            else:
                for c in content or []:
                    parts.append(c.get("text", "") or "" if isinstance(c, dict) else str(c))
        return _strip_html("\n".join(p for p in parts if p))
    except Exception:  # noqa: BLE001
        return ""


def _ashby_jobs(board: str) -> list[dict]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    return data.get("jobs", []) if isinstance(data, dict) else []


def _ashby_location(item: dict) -> str:
    loc = item.get("locationName") or item.get("location") or ""
    if isinstance(loc, dict):
        loc = loc.get("name", "") or ""
    return loc if isinstance(loc, str) else ""


def _ashby_description(item: dict) -> str:
    # The list payload already carries the full text; the single-job
    # endpoint 401s, so there is no detail fetch for Ashby.
    plain = (item.get("descriptionPlain") or "").strip()
    if plain:
        return normalize_ws(plain)
    return _strip_html(item.get("descriptionHtml", ""))


def _remote_type(loc: str) -> str:
    low = (loc or "").lower()
    if "remote" in low:
        return "remote"
    if "hybrid" in low:
        return "hybrid"
    if "on-site" in low or "onsite" in low or "on site" in low:
        return "onsite"
    return ""


def _boards(cfg) -> list[dict]:
    """Configured boards, or the built-in defaults when the list is missing
    or empty. The list is load-bearing: each provider only serves per-company
    endpoints, so there is no 'all Bangalore jobs' query to fall back to."""
    configured = ((cfg.platforms or {}).get("ats", {}) or {}).get("companies")
    if configured:
        return configured
    log.info("ats: no companies configured; using %d default boards",
             len(DEFAULT_COMPANIES))
    return DEFAULT_COMPANIES


def _max_age_days(cfg) -> float:
    """ATS staleness cap. Boards keep serving old reposts; drop anything
    older than this. Kept generous (30d) on purpose: these boards turn over
    slowly, and a 14d cap emptied the entire source in production."""
    try:
        return float((((cfg.platforms or {}).get("ats", {}) or {})
                      .get("max_age_days", 30)))
    except (TypeError, ValueError):  # noqa: BLE001
        return 30.0


def collect_ats(cfg, run_id: str = "") -> list[Job]:
    companies = _boards(cfg)
    max_age_hours = _max_age_days(cfg) * 24
    jobs: list[Job] = []
    for entry in companies:
        provider = (entry.get("provider") or "").lower()
        board = entry.get("board") or ""
        label = entry.get("company") or board
        if not board or provider not in {"greenhouse", "lever", "ashby"}:
            log.warning("ats: skipping bad entry %r", entry)
            continue
        try:
            if provider == "greenhouse":
                raw = _greenhouse_jobs(board)
            elif provider == "lever":
                raw = _lever_jobs(board)
            else:
                raw = _ashby_jobs(board)
        except Exception as e:  # noqa: BLE001
            log.warning("ats %s/%s fetch failed: %s", provider, board, e)
            continue
        kept = 0
        for item in raw:
            job = _map_item(provider, board, label, item)
            if job is None:
                continue
            age = job.age_hours()
            if age is not None and age > max_age_hours:
                continue
            jobs.append(job)
            kept += 1
        log.info("ats %s/%s -> %d jobs (%d kept)", provider, board, len(raw), kept)
    return jobs


def _map_item(provider: str, board: str, label: str, item: dict) -> Job | None:
    try:
        if provider == "greenhouse":
            title = item.get("title", "") or ""
            loc = (item.get("location") or {}).get("name", "") or ""
            url = item.get("absolute_url", "") or ""
            jid = str(item.get("id", ""))
            company = item.get("company_name", "") or label
            posted = _iso(item.get("first_published") or item.get("updated_at"))
            detail = ""
        elif provider == "lever":
            cats = item.get("categories", {}) or {}
            title = item.get("text", "") or ""
            loc = cats.get("location", "") or ""
            url = item.get("hostedUrl", "") or ""
            jid = item.get("id", "") or ""
            company = label
            posted = _iso(item.get("createdAt"))
            detail = ""
        else:  # ashby — list payload already has full text + location
            title = item.get("title", "") or ""
            loc = _ashby_location(item)
            url = item.get("jobUrl", "") or item.get("applyUrl", "") or ""
            jid = item.get("id", "") or ""
            company = label
            posted = _iso(item.get("publishedAt"))
            detail = _ashby_description(item)
        if not title or not url:
            return None
        if not _title_relevant(title):
            return None
        loc = _normalize_location(title, loc)
        if not _in_scope(loc):
            return None
        exp_min, exp_max = parse_years(f"{title}")
        return Job(
            source="ats", source_job_id=f"{provider}:{board}:{jid}",
            canonical_url=url, title=title, company=company, location=loc,
            remote_type=_remote_type(loc), posted_at=posted,
            description_text=detail, apply_type="external_ats",
        )
    except Exception as e:  # noqa: BLE001
        log.debug("ats item skipped: %s", e)
        return None


def enrich_ats(jobs: list[Job]) -> None:
    """Fill descriptions in place (detail fetch only for kept jobs)."""
    for job in jobs:
        if job.description_text and len(job.description_text) >= 100:
            continue
        try:
            provider, board, jid = (job.source_job_id or "").split(":", 2)
        except ValueError:  # noqa: BLE001
            continue
        if provider not in {"greenhouse", "lever", "ashby"} or not board or not jid:
            continue
        try:
            if provider == "greenhouse":
                job.description_text = _greenhouse_detail(board, jid)
            elif provider == "lever":
                job.description_text = _lever_detail(board, jid)
            # ashby: full text already ships in the list payload (see _map_item);
            # the single-job endpoint requires auth, so there is nothing to fetch.
        except Exception as e:  # noqa: BLE001
            log.debug("ats detail failed for %s: %s", job.canonical_url, e)
