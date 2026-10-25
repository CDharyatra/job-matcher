"""Naukri collection + in-platform apply. UI-driven, human-paced, low-volume.

Freshness uses jobAge (days) and sort=dd (date desc). Apply type:
  #apply-button = in-platform (Bucket A); #company-site-button = external (email).
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote

from ..logging_setup import get_logger
from ..models import Job, normalize_posted
from ..textutil import normalize_ws, parse_salary, parse_years
from . import selectors as S
from .pacing import human_scroll, sleep_between
from .session import (BrowserSession, CheckpointError, SessionDeadError, detect_checkpoint,
                       looks_logged_out, wait_for_any_selector)

log = get_logger("jobagent.browser.naukri")

BASE = "https://www.naukri.com"


def build_urls(keywords: str, location: str = "", job_age_days: int = 1,
               page: int = 1) -> list[str]:
    """Candidate search URLs, most-trusted first.

    Shape 1 mirrors the site's own search links (verified in the user's browser):
      /{kw-slug}-jobs-in-{loc}?k={keywords}&jobAge={days}
    Shape 2 is the same without the location path (exactly the user's URL shape).
    Both rely on Naukri's DEFAULT sort, which is Relevance — never force a
    sort param (an old sort=dd shape pinned results to date order against the
    user's explicit Relevance requirement, so it was removed).
    Keywords ride in k= (URL-encoded, comma-separated); freshness in jobAge.
    """
    slug = quote(keywords.strip().lower().replace(" ", "-"), safe="-")
    k = quote(keywords.strip())
    loc = quote((location or "").strip().lower().replace(" ", "-"), safe="-")
    urls = []
    if loc:
        urls.append(f"{BASE}/{slug}-jobs-in-{loc}?k={k}&jobAge={job_age_days}")
    urls.append(f"{BASE}/{slug}-jobs?k={k}&jobAge={job_age_days}")
    if page > 1:
        urls = [u + f"&pageNo={page}" for u in urls]
    return urls


def build_url(keywords: str, location: str = "", job_age_days: int = 1, page: int = 1) -> str:
    """Backwards-compatible: the most-trusted candidate URL."""
    return build_urls(keywords, location, job_age_days, page)[0]


def _t(el, selector: str) -> str:
    try:
        node = el.query_selector(selector)
        return normalize_ws(node.inner_text()) if node else ""
    except Exception:  # noqa: BLE001
        return ""


def _freshness_days(cfg) -> list[int]:
    """Naukri freshness ladder. Locked to [1] (Last 1 day) per explicit user
    requirement — the old [1, 3, 7] widening is what let 3-week-old postings
    like Quantiphi's into the inbox."""
    days = ((cfg.platforms or {}).get("naukri", {}) or {}).get("freshness_days", [1])
    return [int(d) for d in days] or [1]


def collect(session: BrowserSession, queries, cfg, run_id: str = "") -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    cap = cfg.search.daily_collection_cap_per_platform
    page = session.new_page()
    # NOTE: no mnjuser/homepage check. That route intermittently renders a
    # Next.js error shell even in logged-in profiles (observed 2026-09-28).
    # Session health is verified on the first real search page instead: cards
    # loading means the session works; a login form means it does not.
    first_load = True

    age_ladder_days = _freshness_days(cfg)
    for q in queries:
        if len(jobs) >= cap:
            break
        got = 0
        for days in age_ladder_days:
            if got >= cfg.search.min_results_before_widening:
                break
            for page_no in range(1, cfg.search.max_pages_per_query + 1):
                # Try URL shapes until one yields cards; remember the winner.
                won = False
                for url in build_urls(q.keywords, q.location, days, page_no):
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except Exception as e:  # noqa: BLE001
                        log.warning("naukri goto failed: %s", e)
                        continue
                    if detect_checkpoint(page):
                        log.error("checkpoint on naukri; stopping collection")
                        page.close()
                        return jobs
                    if first_load:
                        first_load = False
                        hit = wait_for_any_selector(page, [S.NAUKRI["job_card"]],
                                                    timeout_ms=20000)
                        if hit is None:
                            if looks_logged_out(page):
                                page.close()
                                raise SessionDeadError(
                                    f"naukri: login form shown (url={page.url})")
                            log.warning("naukri first search page has no cards "
                                        "(url=%s title=%r); continuing",
                                        page.url, page.title()[:80])
                    human_scroll(page, steps=2)
                    cards = page.query_selector_all(S.NAUKRI["job_card"])
                    log.info("naukri %s -> %d cards (title=%r)", url, len(cards),
                             page.title()[:80])
                    if cards:
                        won = True
                    else:
                        continue
                    for card in cards:
                        if len(jobs) >= cap:
                            break
                        job = _job_from_card(card)
                        if job and job.canonical_url not in seen:
                            seen.add(job.canonical_url)
                            jobs.append(job)
                            got += 1
                    sleep_between(cfg.apply.min_seconds_between_actions)
                    if len(cards) < 20 or len(jobs) >= cap:
                        break
                    break  # shape won; next page
                if not won:
                    break  # no shape loaded results; widen freshness instead
    _enrich_newest(session, jobs, cfg)
    page.close()
    log.info("naukri collected %d jobs", len(jobs))
    return jobs


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
            log.info("naukri detail %d/%d: %s | %s | %s", done, cap,
                     (job.title or "?")[:70], job.company or "?",
                     job.apply_type)
        except CheckpointError:
            log.error("checkpoint during naukri enrich; stopping enrich")
            break
        except Exception as e:  # noqa: BLE001
            log.warning("enrich failed for %s: %s", job.canonical_url, e)
        sleep_between(cfg.apply.min_seconds_between_actions)
    log.info("naukri detail enrich complete: %d enriched", done)


def _attr(el, name: str) -> str:
    try:
        return normalize_ws(el.get_attribute(name) or "") if el is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def _job_from_card(card) -> Job | None:
    try:
        link = card.query_selector("a.title, a.jobTitle, a[href*='job-listings']")
        href = (link.get_attribute("href") if link else "") or ""
        if href and href.startswith("/"):
            href = BASE + href
        # Live markup (verified 2026-09-28) carries full text in title attrs:
        # <a class="title" title="Lead/Senior Domino Data Lab with Python" ...>
        title = _attr(link, "title") or _t(card, S.NAUKRI["card_title"])
        comp_el = card.query_selector("a.comp-name, a.subTitle, .companyInfo a")
        company = _attr(comp_el, "title") or _t(card, S.NAUKRI["card_company"])
        location = _t(card, S.NAUKRI["card_location"])
        posted = _t(card, S.NAUKRI["card_posted"])
        salary = _t(card, S.NAUKRI["card_salary"])
        exp = _t(card, S.NAUKRI["card_experience"])
        # Skill tags are free structured signals: <li class="tag-li">Python</li>
        tags = []
        try:
            for tag_el in card.query_selector_all("li.tag-li"):
                tag_text = normalize_ws(tag_el.inner_text())
                if tag_text:
                    tags.append(tag_text)
        except Exception:  # noqa: BLE001
            pass
        # Card snippet; the detail page overwrites this with the full text.
        snippet = _t(card, "span.job-desc")
        jid = _attr(card, "data-job-id")
        if not jid:
            # The numeric job id is the LAST dash-group before ? or end of path.
            # (End-anchored: an earlier "-4-to-9-years" must not match as id "4".)
            m = re.search(r"-(\d+)(?:\?|$)", href)
            if m:
                jid = m.group(1)
        lo, hi, cur = parse_salary(salary)
        jmin, jmax = parse_years(exp)
        if (jmin is None or jmax is None) and href:
            # Fallback: the URL itself carries "...-4-to-9-years-{jobid}".
            mu = re.search(r"(\d+)-to-(\d+)-years", href)
            if mu:
                jmin = jmin if jmin is not None else float(mu.group(1))
                jmax = jmax if jmax is not None else float(mu.group(2))
        if not (title or href):
            return None
        return Job(
            source="naukri", source_job_id=jid, canonical_url=href,
            title=title, company=company, location=location,
            posted_at=normalize_posted(posted),
            description_text=snippet,
            requirements=", ".join(tags),
            salary_raw=salary, salary_min=lo, salary_max=hi, salary_currency=cur,
            experience_min=jmin, experience_max=jmax,
            apply_type="unknown",
        )
    except Exception as e:  # noqa: BLE001
        log.debug("naukri card skipped: %s", e)
        return None


def enrich_from_detail(session: BrowserSession, job: Job, cfg) -> Job:
    page = session.new_page()
    try:
        page.goto(job.canonical_url, wait_until="domcontentloaded")
        if detect_checkpoint(page):
            raise CheckpointError("naukri detail checkpoint")
        # Detail content hydrates client-side; wait for it before reading.
        wait_for_any_selector(page, [
            S.NAUKRI["detail_description"],
            S.NAUKRI["in_platform_apply"],
            S.NAUKRI["company_site_apply"],
        ], timeout_ms=20000)
        desc = _t(page, S.NAUKRI["detail_description"])
        if len(desc) >= 100:
            job.description_text = desc
        elif desc and not job.description_text:
            job.description_text = desc
        if page.query_selector(S.NAUKRI["company_site_apply"]):
            job.apply_type = "external_ats"
        elif page.query_selector(S.NAUKRI["in_platform_apply"]):
            job.apply_type = "naukri_apply"
        return job
    finally:
        page.close()


def _find_apply_control(page) -> str:
    """Classify the apply path after waiting for hydration.

    Returns apply | external | applied | none. "applied" means the account
    already applied (manual or earlier run): no button exists because there
    is nothing left to do. Checked first so it is never misread as "none".
    """
    wait_for_any_selector(page, [S.NAUKRI["in_platform_apply"],
                                 S.NAUKRI["company_site_apply"],
                                 S.NAUKRI["already_applied"]],
                          timeout_ms=20000)
    if page.query_selector(S.NAUKRI["already_applied"]):
        return "applied"
    if page.query_selector(S.NAUKRI["company_site_apply"]):
        return "external"
    if page.query_selector(S.NAUKRI["in_platform_apply"]):
        return "apply"
    return "none"


def in_platform_apply(session: BrowserSession, job: Job, facts, cfg, resume_path: str,
                      autofill) -> tuple[bool, str]:
    page = session.new_page()
    try:
        page.goto(job.canonical_url, wait_until="domcontentloaded")
        if detect_checkpoint(page):
            return False, "checkpoint"
        kind = _find_apply_control(page)
        if kind == "applied":
            return False, "already applied on this account; nothing to submit"
        if kind == "external":
            return False, "apply on company website (external) -> inbox"
        if kind == "none":
            return False, "no in-platform apply button"
        btn = page.query_selector(S.NAUKRI["in_platform_apply"])
        if not btn:
            return False, "apply button vanished before click"
        btn.click()
        time.sleep(cfg.apply.min_seconds_between_actions)
        # recruiter questions may appear (chatbot modal with a contenteditable
        # box, or legacy inline inputs); fill deterministically.
        # Loop: answering one question can reveal the next.
        missing: list[str] = []
        for _ in range(3):
            missing = autofill.fill_naukri_questions(page, facts)
            if missing:
                return False, f"missing facts: {','.join(missing)}"
            time.sleep(2)
            # Another question may have appeared after answering.
            try:
                more = autofill.fill_naukri_questions(page, facts)
            except Exception:  # noqa: BLE001
                more = []
            if not more:
                break
            missing = more
        if missing:
            return False, f"missing facts: {','.join(missing)}"
        for label in ("Submit", "Save & Apply", "Apply", "Save"):
            el = page.query_selector(f"button:has-text('{label}')")
            if el:
                try:
                    if not (el.is_visible() and el.is_enabled()):
                        continue
                except Exception:  # noqa: BLE001
                    pass
                try:
                    el.click(timeout=8000)
                except Exception:  # noqa: BLE001
                    try:
                        # Chatbot overlays (.chatbot_Overlay.show) intercept
                        # pointer events at the button point, so a strict
                        # click retries until timeout. Force-dispatch instead.
                        el.click(force=True, timeout=8000)
                    except Exception as e:  # noqa: BLE001
                        return False, f"submit click blocked: {str(e)[:120]}"
                time.sleep(cfg.apply.min_seconds_between_actions)
                # Positive evidence only: the apply control must flip to the
                # already-applied marker (never infer success from a click).
                try:
                    if page.query_selector(S.NAUKRI["already_applied"]):
                        return True, "submitted"
                    blob = normalize_ws(page.evaluate(
                        "() => document.body.innerText.slice(0,4000)") or "").lower()
                    if any(m in blob for m in ("successfully applied", "application submitted", "applied successfully")):
                        return True, "submitted"
                except Exception:  # noqa: BLE001
                    pass
                return False, "save clicked without applied evidence"
        return False, "no submit control reached"
    except CheckpointError:
        return False, "checkpoint"
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"
    finally:
        page.close()