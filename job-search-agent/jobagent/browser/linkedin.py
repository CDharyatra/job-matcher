"""LinkedIn collection + Easy Apply. UI-driven, human-paced, low-volume.

Job search URL params (see RESEARCH.md A.6):
  f_TPR in seconds (86400=24h, 604800=7d), f_AL=true Easy Apply, f_WT=2 remote.
LinkedIn is migrating its search UI; selectors degrade gracefully.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from ..logging_setup import get_logger
from ..models import Job, normalize_posted
from ..textutil import normalize_ws, parse_years, parse_salary
from . import selectors as S
from .pacing import human_scroll, sleep_between
from .session import (BrowserSession, CheckpointError, SessionDeadError, detect_checkpoint,
                      require_logged_in, wait_for_any_selector)

import re

log = get_logger("jobagent.browser.linkedin")

# Verified 2026-09-28 in the user's browser: the current search UI lives at
# /jobs/search-results/ (not /jobs/search/), with keywords= and f_TPR=r86400
# for "Past 24 hours". Selecting a job adds ?currentJobId={id}.
BASE = "https://www.linkedin.com/jobs/search-results/"


def build_url(keywords: str, location: str = "", hours: int = 24,
              easy_apply: bool = False, remote: bool = False, page: int = 1) -> str:
    params = {"keywords": keywords, "f_TPR": f"r{hours * 3600}"}
    if location:
        params["location"] = location
    if easy_apply:
        params["f_AL"] = "true"
    if remote:
        params["f_WT"] = "2"
    if page > 1:
        params["start"] = str((page - 1) * 25)
    return f"{BASE}?{urlencode(params)}"


def _first_text(card, selector: str) -> str:
    try:
        el = card.query_selector(selector)
        if el:
            return normalize_ws(el.inner_text())
    except Exception:  # noqa: BLE001
        pass
    return ""


def search_passes(cfg) -> list[bool]:
    """Easy Apply pass first (auto-apply inventory), then the all-jobs pass so
    external postings can still reach the inbox. Each enabled once."""
    passes = []
    plats = cfg.platforms.get("linkedin", {})
    if plats.get("easy_apply_pass", True):
        passes.append(True)
    if plats.get("all_jobs_pass", True):
        passes.append(False)
    return passes or [True]


def collect(session: BrowserSession, queries, cfg, run_id: str = "") -> list[Job]:
    """Walk LinkedIn search pages. Returns normalized Job records (no apply)."""
    jobs: list[Job] = []
    seen: set[str] = set()
    platform_cap = cfg.search.daily_collection_cap_per_platform
    page = session.new_page()
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        require_logged_in(page, S.LINKEDIN["logged_in"], "linkedin",
                          fallbacks=S.LINKEDIN.get("logged_in_fallbacks"))
    except (SessionDeadError, CheckpointError) as e:
        log.error("linkedin session unusable: %s", e)
        page.close()
        raise

    ladder = cfg.search.date_posted_ladder_hours or [24]
    for easy_apply in search_passes(cfg):
        for q in queries:
            if len(jobs) >= platform_cap:
                break
            got_for_query = 0
            for hours in ladder:
                if got_for_query >= cfg.search.min_results_before_widening:
                    break
                for page_no in range(1, cfg.search.max_pages_per_query + 1):
                    url = build_url(q.keywords, q.location, hours,
                                    easy_apply=easy_apply,
                                    remote=q.remote, page=page_no)
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except Exception as e:  # noqa: BLE001
                        log.warning("goto failed: %s", e)
                        break
                    if detect_checkpoint(page):
                        log.error("checkpoint on linkedin search; stopping collection")
                        page.close()
                        return jobs
                    human_scroll(page, steps=2)
                    # Results stream in client-side; wait for hydration first.
                    wait_for_any_selector(page, S.LINKEDIN["hydration_markers"],
                                          timeout_ms=25000)
                    cards = page.query_selector_all(S.LINKEDIN["job_card"])
                    harvested = _harvest_all(page)
                    if not cards and not harvested:
                        log.info("linkedin %s -> empty page (title=%r)", url,
                                 page.title()[:80])
                        break
                    new_before = len(seen)
                    for card in cards:
                        if len(jobs) >= platform_cap:
                            break
                        job = _job_from_card(card, q, page)
                        if job and job.canonical_url not in seen:
                            seen.add(job.canonical_url)
                            jobs.append(job)
                            got_for_query += 1
                    for jid, text in harvested:
                        if len(jobs) >= platform_cap:
                            break
                        url_id = f"https://www.linkedin.com/jobs/view/{jid}/"
                        if url_id not in seen:
                            seen.add(url_id)
                            jobs.append(Job(
                                source="linkedin", source_job_id=jid, canonical_url=url_id,
                                title=(text or "").split("\n")[0][:120],
                                apply_type="unknown",
                            ))
                            got_for_query += 1
                    log.info("linkedin %s -> %d cards, %d ids, %d new (title=%r)",
                             url, len(cards), len(harvested), len(seen) - new_before,
                             page.title()[:80])
                    sleep_between(cfg.apply.min_seconds_between_actions)
                    if len(cards) < 25 and not harvested:
                        break
    _enrich_newest(session, jobs, cfg)
    page.close()
    log.info("linkedin collected %d jobs", len(jobs))
    return jobs


def _harvest_ids(page) -> list[tuple[str, str]]:
    """Job ids from any currentJobId link, with anchor text as a title hint."""
    try:
        items = page.eval_on_selector_all(
            S.LINKEDIN["card_link"],
            "els => els.map(e => ({href: e.getAttribute('href') || '', "
            "text: (e.innerText || '').trim()}))",
        )
    except Exception:  # noqa: BLE001
        return []
    return _ids_from_items(items or [])


# Anchor texts that are UI chrome, not job titles ("More" and "Hybrid" both
# scored as jobs once). Exact match only — real titles containing these words
# ("Hybrid Cloud Engineer") are untouched.
JUNK_TITLES = {"more", "show more", "see more", "show all", "view more",
               "view all", "view all jobs", "see all jobs", "hybrid", "remote",
               "onsite", "on-site", "full-time", "part-time"}


def _ids_from_items(items: list[dict]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for item in items:
        m = re.search(r"[?&]currentJobId=(\d+)", item.get("href") or "")
        text = (item.get("text") or "").strip()
        if m and m.group(1) not in seen_ids and text.lower() not in JUNK_TITLES:
            seen_ids.add(m.group(1))
            out.append((m.group(1), text))
    return out


def enrich_from_text(job: Job, doc_title: str = "", body_text: str = "") -> Job:
    """Fill gaps from the document title and rendered body text.

    Observed live format: <title>"Title | Company | LinkedIn"</title>,
    a "<span>City (Remote|Hybrid|On-site)</span>" location line, and a
    "India · 3 hours ago · Over 100 applicants" meta line. Used only for
    fields the selectors missed — never overwrites real values.
    """
    if doc_title and "|" in doc_title:
        parts = [p.strip() for p in doc_title.split("|")]
        if not job.title and len(parts) >= 1 and "linkedin" not in parts[0].lower():
            job.title = parts[0][:120]
        if not job.company and len(parts) >= 2 and "linkedin" not in parts[1].lower():
            job.company = parts[1][:120]
    if body_text:
        if not job.location:
            # inner_text separates blocks with newlines, so match per line:
            # a "City (Remote|Hybrid|On-site)" line is the location line.
            for line in body_text.splitlines():
                m = re.search(r"^\s*(.+?)\s*\(\s*(Remote|Hybrid|On-?site)\s*\)\s*$",
                              line.strip())
                if m and len(m.group(1)) <= 60:
                    job.location = normalize_ws(m.group(1))
                    job.remote_type = ("remote" if m.group(2).lower() == "remote"
                                       else "hybrid")
                    break
        if not job.posted_at:
            m = re.search(r"(?:Posted\s+)?(\d+\s+(?:minute|hour|day|week|month)s?\s+ago"
                          r"|Just now|Reposted\s+\d+\s+\w+\s+ago)", body_text,
                          re.IGNORECASE)
            if m:
                job.posted_at = normalize_posted(m.group(1)) or job.posted_at
        if job.applicant_count is None:
            m = re.search(r"((?:Over|Less than|about)\s+)?([\d,]+)\s+applicants?",
                          body_text, re.IGNORECASE)
            if m:
                try:
                    job.applicant_count = int(m.group(2).replace(",", ""))
                except ValueError:
                    pass
    return job


def _harvest_all(page, rounds: int = 3) -> list[tuple[str, str]]:
    """Scroll-and-reharvest: results stream in, so one snapshot is not enough."""
    acc: list[tuple[str, str]] = []
    known: set[str] = set()
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        html = ""
    # The server-rendered SDUI shell already names every card on the page
    # (job-card-component-ref-{id}); anchors confirm what actually rendered.
    for jid in _ids_from_content(html):
        if jid not in known:
            known.add(jid)
            acc.append((jid, ""))
    for _ in range(rounds):
        for jid, text in _harvest_ids(page):
            if jid not in known:
                known.add(jid)
                acc.append((jid, text))
            elif text and not dict(acc).get(jid):
                acc = [(i, text if i == jid else t) for i, t in acc]
        human_scroll(page, steps=2)
        sleep_between(1)
    return acc


def _ids_from_content(html: str) -> list[str]:
    """Job ids embedded in the page's own data shell (instant, complete)."""
    out: list[str] = []
    for pat in (r"job-card-component-ref-(\d+)", r"currentJobId=(\d+)"):
        for m in re.finditer(pat, html or ""):
            if m.group(1) not in out:
                out.append(m.group(1))
    return out


def _enrich_newest(session: BrowserSession, jobs: list[Job], cfg) -> None:
    """Open detail pages newest-first (up to the cap) to fill descriptions."""
    cap = getattr(cfg.search, "max_details_per_run", 50)
    dated = sorted((j for j in jobs if j.posted_at), key=lambda j: j.posted_at,
                   reverse=True)
    undated = [j for j in jobs if not j.posted_at]
    done = 0
    for job in dated + undated:
        if done >= cap:
            break
        if len(job.description_text or "") >= 100:
            continue
        try:
            enrich_from_detail(session, job, cfg)
            done += 1
            log.info("linkedin detail %d/%d: %s | %s | %s", done, cap,
                     (job.title or "?")[:70], job.company or "?",
                     job.apply_type)
        except CheckpointError:
            log.error("checkpoint during linkedin enrich; stopping enrich")
            break
        except Exception as e:  # noqa: BLE001
            log.warning("enrich failed for %s: %s", job.canonical_url, e)
        sleep_between(cfg.apply.min_seconds_between_actions)
    log.info("linkedin detail enrich complete: %d enriched", done)


def _job_from_card(card, q, page) -> Job | None:
    try:
        title = _first_text(card, S.LINKEDIN["card_title"])
        company = _first_text(card, S.LINKEDIN["card_company"])
        location = _first_text(card, S.LINKEDIN["card_location"])
        posted_raw = ""
        try:
            t = card.query_selector(S.LINKEDIN["card_posted"])
            posted_raw = normalize_ws(t.get_attribute("datetime") or t.inner_text()) if t else ""
        except Exception:  # noqa: BLE001
            pass
        link = card.query_selector(S.LINKEDIN["card_title"])
        href = ""
        if link:
            href = link.get_attribute("href") or ""
        if href and href.startswith("/"):
            href = "https://www.linkedin.com" + href
        jid = ""
        import re
        m = re.search(r"/jobs/view/(\d+)", href or "")
        if m:
            jid = m.group(1)
        if not jid:
            # New search UI links cards as /jobs/search-results/?currentJobId={id}
            m2 = re.search(r"[?&]currentJobId=(\d+)", href or "")
            if m2:
                jid = m2.group(1)
        if jid:
            # Normalize away tracking params for a stable canonical URL + dedup.
            href = f"https://www.linkedin.com/jobs/view/{jid}/"
        if not (title or href):
            return None
        return Job(
            source="linkedin", source_job_id=jid, canonical_url=href or "",
            title=title, company=company, location=location,
            remote_type="remote" if "remote" in location.lower() else "",
            posted_at=normalize_posted(posted_raw),
            apply_type="unknown",
        )
    except Exception as e:  # noqa: BLE001
        log.debug("card parse skipped: %s", e)
        return None


def enrich_from_detail(session: BrowserSession, job: Job, cfg) -> Job:
    """Open the job page to read full description, salary, applicant count, apply type."""
    page = session.new_page()
    try:
        page.goto(job.canonical_url, wait_until="domcontentloaded")
        if detect_checkpoint(page):
            raise CheckpointError("linkedin detail checkpoint")
        # Detail content hydrates client-side; wait for it before reading.
        wait_for_any_selector(page, [
            S.LINKEDIN["detail_description"],
            S.LINKEDIN["easy_apply_button"],
            S.LINKEDIN["external_apply_link"],
        ], timeout_ms=20000)
        # Read-only expansion so truncated descriptions are read in full.
        # (Expanding text is not a submit; failures are ignored.)
        try:
            more = page.query_selector("button:has-text('Show more'), button:has-text('See more')")
            if more:
                more.click()
                time.sleep(2)
        except Exception:  # noqa: BLE001
            pass
        # Fall back to the document title ("Title | Company | LinkedIn") and
        # rendered body text for fields the selectors missed.
        try:
            body_text = page.inner_text("body")
        except Exception:  # noqa: BLE001
            body_text = ""
        enrich_from_text(job, page.title() or "", body_text or "")
        merge_detail(job, {
            "description_text": _first_text(page, S.LINKEDIN["detail_description"]),
            "salary_raw": _first_text(page, S.LINKEDIN["detail_salary"]),
            "posted_raw": _first_text(page, S.LINKEDIN["detail_posted"]),
            "applicants_raw": _first_text(page, S.LINKEDIN["applicant_count"]),
        })
        if page.query_selector(S.LINKEDIN["easy_apply_button"]):
            job.apply_type = "easy_apply"
        elif page.query_selector(S.LINKEDIN["external_apply_link"]):
            job.apply_type = "external_ats"
        return job
    finally:
        page.close()


def merge_detail(job: Job, detail: dict) -> Job:
    """Merge freshly read detail fields WITHOUT wiping existing card data."""
    desc = detail.get("description_text") or ""
    if len(desc) >= 100:
        job.description_text = desc
    elif desc and not job.description_text:
        job.description_text = desc
    salary = detail.get("salary_raw") or ""
    if salary:
        lo, hi, cur = parse_salary(salary)
        job.salary_raw = salary
        job.salary_min, job.salary_max, job.salary_currency = lo, hi, cur
    if desc:
        jmin, jmax = parse_years(desc)
        if jmin is not None and job.experience_min is None:
            job.experience_min = jmin
        if jmax is not None and job.experience_max is None:
            job.experience_max = jmax
    posted = detail.get("posted_raw") or ""
    if posted:
        job.posted_at = normalize_posted(posted) or job.posted_at
    applicants = detail.get("applicants_raw") or ""
    if applicants:
        m = re.search(r"(\d+)", applicants)
        if m:
            job.applicant_count = int(m.group(1))
    return job


def _find_apply_control(page) -> str:
    """Classify the apply path after waiting for hydration: easy|external|none.

    The detail page renders client-side; querying instantly (as before) misses
    controls that enrich — minutes earlier, with a wait — had already seen.
    """
    wait_for_any_selector(page, [S.LINKEDIN["easy_apply_button"],
                                 S.LINKEDIN["external_apply_link"]],
                          timeout_ms=20000)
    if page.query_selector(S.LINKEDIN["easy_apply_button"]):
        return "easy"
    if page.query_selector(S.LINKEDIN["external_apply_link"]):
        return "external"
    return "none"


def find_easy_apply_dialog(page):
    """The live Easy Apply surface: a native <dialog> (no role attribute)."""
    for sel in ("dialog.open[data-testid='dialog']",
                "dialog[open][data-testid='dialog']",
                "dialog[open]"):
        try:
            el = page.query_selector(sel)
            if el:
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


def find_easy_apply_dialog(page):
    """The live Easy Apply surface: a native <dialog> (no role attribute)."""
    for sel in S.LINKEDIN["modal"].split(","):
        try:
            el = page.query_selector(sel.strip())
            if el:
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


def _dialog_button(dialog, *labels: str):
    """First visible dialog button matching any label (exact, case-insensitive)."""
    try:
        buttons = dialog.query_selector_all("button")
    except Exception:  # noqa: BLE001
        return None
    for label in labels:
        want = label.strip().lower()
        for btn in buttons:
            try:
                text = ((btn.get_attribute("aria-label") or btn.inner_text())
                        or "").strip().lower()
            except Exception:  # noqa: BLE001
                continue
            if text and (text == want or text.startswith(want + " ")):
                try:
                    if btn.is_visible() and btn.is_enabled():
                        return btn
                except Exception:  # noqa: BLE001
                    continue
    return None


SUCCESS_MARKERS = (
    "application sent", "successfully applied", "application was submitted",
    "application submitted", "your application was sent",
)


def _dialog_success(page) -> bool:
    """Positive evidence of a completed submit: success text in an open dialog,
    toast, or alert. Never infer success from a closed dialog alone."""
    try:
        texts = []
        dialog = find_easy_apply_dialog(page)
        if dialog is not None:
            texts.append(dialog.inner_text() or "")
        for sel in (".artdeco-toast-item", "[role='alert']", "[role='status']"):
            try:
                for el in page.query_selector_all(sel):
                    texts.append(el.inner_text() or "")
            except Exception:  # noqa: BLE001
                continue
        blob = " ".join(texts).lower()
        return any(m in blob for m in SUCCESS_MARKERS)
    except Exception:  # noqa: BLE001
        return False


def easy_apply(session: BrowserSession, job: Job, facts, cfg, resume_path: str,
               autofill) -> tuple[bool, str]:
    """Open the Easy Apply dialog and submit. Returns (success, detail).

    Hard rules: never invent a blank fact; on a missing fact, fail that job and
    name the field. On checkpoint, stop and mark failed (do not bypass). Only
    forward actions (Next/Review/Continue/Submit) are ever clicked — Dismiss,
    Discard, Back, and Cancel are never touched. A submit counts only with
    positive on-page evidence, never from a closed dialog alone.
    """
    page = session.new_page()
    try:
        page.goto(job.canonical_url, wait_until="domcontentloaded")
        if detect_checkpoint(page):
            return False, "checkpoint"
        kind = _find_apply_control(page)
        if kind == "external":
            return False, "external apply (leaves LinkedIn) -> inbox"
        if kind == "none":
            return False, "no Easy Apply button (external or removed)"
        btn = page.query_selector(S.LINKEDIN["easy_apply_button"])
        if not btn:
            return False, "apply button vanished before click"
        btn.click()
        time.sleep(cfg.apply.min_seconds_between_actions)

        for _ in range(12):  # multi-step dialog
            if detect_checkpoint(page):
                return False, "checkpoint"
            dialog = find_easy_apply_dialog(page)
            if dialog is None:
                # Dialog gone: submitted (verify) or dismissed/crashed (fail).
                if _dialog_success(page):
                    return True, "submitted"
                return False, "dialog closed without submit evidence"
            missing, notes = autofill.fill_dialog(page, facts, resume_path)
            for note in notes:
                log.debug("autofill note: %s", note)
            if missing:
                return False, f"missing facts: {','.join(missing)}"
            if _dialog_success(page):
                return True, "submitted"
            clicked = _dialog_button(dialog, "Submit application", "Submit")
            if clicked is None:
                clicked = _dialog_button(dialog, "Review your application", "Review")
            if clicked is None:
                clicked = _dialog_button(dialog, "Next", "Continue")
            if clicked is None:
                return False, "modal did not reach submit"
            clicked.click()
            time.sleep(cfg.apply.min_seconds_between_actions)
        return False, "modal did not reach submit"
    except CheckpointError:
        return False, "checkpoint"
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"
    finally:
        page.close()