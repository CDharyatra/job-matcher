"""Parse LinkedIn and Naukri job-alert emails into Job records.

Regex/HTML based, deterministic, no LLM. This is the fallback intake channel that
keeps the pipeline alive when a live session is challenged.
"""

from __future__ import annotations

import html as htmlmod
import re
import urllib.parse

from ..logging_setup import get_logger
from ..models import Job
from ..textutil import normalize_ws
from .reader import RawEmail

log = get_logger("jobagent.mail.alerts")

LI_DOMAINS = ("linkedin.com", "lnkd.in")
NAUKRI_DOMAINS = ("naukri.com",)


def _hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


def _text_of(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return htmlmod.unescape(text)


def parse_email(raw: RawEmail) -> list[Job]:
    blob = raw.html or raw.text
    low = blob.lower()
    if any(d in low for d in LI_DOMAINS) and "job" in low:
        return _parse_linkedin(raw)
    if any(d in low for d in NAUKRI_DOMAINS):
        return _parse_naukri(raw)
    return []


def _clean_li_url(url: str) -> str:
    m = re.search(r"(https?://[a-z]{0,3}\.?linkedin\.com/jobs/view/[^?\"&]+)", url)
    return m.group(1) if m else url


def _parse_linkedin(raw: RawEmail) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    for url in _hrefs(raw.html):
        if "/jobs/view/" not in url:
            continue
        clean = _clean_li_url(url)
        if clean in seen:
            continue
        seen.add(clean)
        jobs.append(Job(
            source="linkedin", canonical_url=clean,
            apply_type="unknown", raw_payload=raw.uid,
        ))
    if not jobs:
        # text-only fallback: pull job ids
        for jid in set(re.findall(r"/jobs/view/(\d+)", raw.text)):
            jobs.append(Job(source="linkedin",
                            canonical_url=f"https://www.linkedin.com/jobs/view/{jid}",
                            source_job_id=jid, apply_type="unknown", raw_payload=raw.uid))
    log.info("linkedin alert %s -> %d jobs", raw.subject[:40], len(jobs))
    return jobs


def _unwrap_redirect(href: str) -> str:
    """Tracking links (tr.naukri.com?data=...&redirect=<url-encoded>) carry the
    real destination in a redirect= parameter. Return it when present."""
    try:
        qs = urllib.parse.urlparse(htmlmod.unescape(href)).query
        vals = urllib.parse.parse_qs(qs).get("redirect")
        if vals:
            return urllib.parse.unquote(vals[0])
    except Exception:  # noqa: BLE001
        pass
    return href


def _parse_naukri(raw: RawEmail) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()

    def add(clean: str, title: str = "") -> None:
        clean = clean.split("?")[0]  # drop utm_* tracking params
        if not clean or clean in seen:
            return
        seen.add(clean)
        jid = re.search(r"-(\d+)$", clean)
        exp_lo = exp_hi = None
        mu = re.search(r"(\d+)-to-(\d+)-years", clean)
        if mu:
            exp_lo, exp_hi = float(mu.group(1)), float(mu.group(2))
        jobs.append(Job(
            source="naukri", canonical_url=clean,
            source_job_id=jid.group(1) if jid else "",
            title=normalize_ws(htmlmod.unescape(title))[:120],
            experience_min=exp_lo, experience_max=exp_hi,
            apply_type="unknown", raw_payload=raw.uid,
        ))

    html = raw.html or ""
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html,
                         flags=re.S | re.I):
        href, inner = m.group(1), m.group(2)
        text = normalize_ws(re.sub(r"<[^>]+>", " ", inner))
        for cand in (_unwrap_redirect(href), href):
            mm = re.search(r"(https?://[^\"']*naukri\.com/(?:job-listings|jobs)[^\"'?]*)",
                           cand)
            if mm:
                add(mm.group(1), text)
                break
    if not jobs:
        # text-only fallback: bare job-listings URLs pasted as text
        for m in set(re.findall(
                r"https?://[^\s\"']*naukri\.com/(?:job-listings|jobs)[^\s\"'?]*",
                raw.text or "")):
            add(m)
    log.info("naukri alert %s -> %d jobs", raw.subject[:40], len(jobs))
    return jobs


def rank_alert_jobs(raw: RawEmail) -> str:
    return normalize_ws(raw.subject)