"""Build the inbox digest email: packets for Bucket B, above-90, failed applies."""

from __future__ import annotations

from datetime import datetime, timezone

from .matcher import MatchResult
from .models import Job


def _fmt_posted(job: Job) -> str:
    if not job.posted_at:
        return "unknown"
    return job.posted_at[:16].replace("T", " ")


def packet_html(job: Job, result: MatchResult, dry_run: bool = False) -> str:
    salary = job.salary_raw or "not disclosed"
    evidence = "".join(
        f"<li>{e.get('requirement','')} &mdash; {e.get('resume_signal','')}</li>"
        for e in (result.evidence or [])[:8]
    )
    reasons = "; ".join(result.reasons[:6])
    missing = ", ".join(result.decision.missing_facts) or "none"
    banner = "<p><b>DRY RUN — would have applied</b></p>" if dry_run else ""
    return f"""
    <div style="border:1px solid #ddd;border-radius:8px;padding:12px;margin:10px 0;font-family:sans-serif">
      <h3 style="margin:0 0 4px">{job.title or 'Untitled'}</h3>
      <p style="margin:0;color:#444">{job.company or 'Unknown company'} &middot; {job.location or 'n/a'}</p>
      <p style="margin:4px 0;color:#666">Posted: {_fmt_posted(job)} &middot; Source: {job.source} &middot; Apply: {job.apply_type}</p>
      <p style="margin:4px 0">Match: <b>{result.overall_match}</b> &middot; Salary: {salary}</p>
      {banner}
      <p style="margin:6px 0"><b>Why it matched:</b> {reasons}</p>
      <ul style="margin:6px 0 6px 18px">{evidence}</ul>
      <p style="margin:4px 0"><b>Missing fact (if any):</b> {missing}</p>
      <p style="margin:8px 0">
        <a href="{job.canonical_url}">Open job</a> &nbsp;|&nbsp;
        Reply: <b>I applied</b> / <b>skip</b> / <b>never this company</b>
      </p>
    </div>
    """


def prioritize(items: list[tuple[Job, MatchResult]], limit: int
               ) -> tuple[list[tuple[Job, MatchResult]], int]:
    """Best-first ordering for the digest: score desc, recency as tiebreak.

    Returns (top_items, overflow_count). Overflow is NOT marked emailed/dryrun,
    so it competes again next run — nothing vanishes silently.
    """
    limit = max(1, int(limit or 0))
    by_recency = sorted(items, key=lambda jr: jr[0].posted_at or "", reverse=True)
    ranked = sorted(by_recency, key=lambda jr: jr[1].overall_match, reverse=True)
    return ranked[:limit], max(0, len(ranked) - limit)


def gaps_html(gaps: list[dict]) -> str:
    if not gaps:
        return ""
    rows = "".join(
        f"<li><b>{g['skill']}</b> &mdash; demanded in {g['jobs']} relevant jobs"
        + (f" (e.g. {g['example']})" if g.get("example") else "") + "</li>"
        for g in gaps
    )
    return ("<h3>Skill gaps to upskill</h3>"
            "<p style='color:#666'>Skills the market keeps asking for that are not "
            "on the resume. Learn these to convert near-misses into matches.</p>"
            f"<ul>{rows}</ul>")


def build_digest(run_id: str, inbox_items: list[tuple[Job, MatchResult]],
                 applied_items: list[tuple[Job, MatchResult]],
                 failed_items: list[tuple[Job, MatchResult]],
                 summary: dict, dry_run: bool = False,
                 gaps: list[dict] | None = None) -> tuple[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = "Job Agent — dry run" if dry_run else "Job Agent — digest"
    parts = [
        f"<h2>{title}</h2>",
        f"<p style='color:#666'>{ts} &middot; run {run_id}</p>",
        "<h3>Summary</h3>",
        "<ul>" + "".join(f"<li>{k}: {v}</li>" for k, v in summary.items()) + "</ul>",
    ]
    if applied_items:
        parts.append("<h3>Auto-applied (70-90)</h3>")
        parts += [packet_html(j, r, dry_run=dry_run) for j, r in applied_items]
    if inbox_items:
        parts.append("<h3>Inbox — needs a human look</h3>")
        parts += [packet_html(j, r) for j, r in inbox_items]
    if failed_items:
        parts.append("<h3>Apply attempted and failed — apply yourself</h3>")
        parts += [packet_html(j, r) for j, r in failed_items]
    parts.append(gaps_html(gaps or []))
    html = "".join(parts)
    text = html.replace("<li>", "\n- ").replace("</li>", "")
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return html, text