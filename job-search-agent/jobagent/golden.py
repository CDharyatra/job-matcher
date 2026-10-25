"""Build the golden-set labeling file from real collected jobs.

`python -m jobagent.cli golden` writes labels/golden_set.yaml with stratified
jobs (top, middle, bottom by system score) and blank labels. A human fills
label: apply | inbox | discard on each, then `cli eval` measures auto-apply
precision. No labels invented, ever.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import paths
from .database import Store
from .logging_setup import get_logger

log = get_logger("jobagent.golden")

LABELS = ("apply", "inbox", "discard")


def build_golden_entries(store: Store, n: int = 50) -> list[dict]:
    rows = store.scored_jobs()
    if not rows:
        return []
    n = min(n, len(rows))
    n_top = max(1, int(n * 0.4))
    n_bottom = max(1, int(n * 0.2))
    n_mid = n - n_top - n_bottom
    mid_start = max(0, (len(rows) - n_mid) // 2)
    picked = (rows[:n_top]
              + rows[mid_start:mid_start + n_mid]
              + rows[len(rows) - n_bottom:])
    entries = []
    for r in picked:
        entries.append({
            "title": r.get("title") or "",
            "company": r.get("company") or "",
            "location": r.get("location") or "",
            "source": r.get("source") or "",
            "url": r.get("canonical_url") or "",
            "apply_type": r.get("apply_type") or "unknown",
            "experience_min": r.get("experience_min"),
            "experience_max": r.get("experience_max"),
            "salary_raw": r.get("salary_raw") or "",
            "posted_at": r.get("posted_at"),
            "description": r.get("description_text") or "",
            "system_score": r.get("score"),
            "system_bucket": r.get("bucket"),
            "label": "",
        })
    return entries


def load_existing(path: Path | None) -> list[dict]:
    """Existing entries (labels intact). Empty list when no file yet."""
    path = path or (paths.HOME / "labels" / "golden_set.yaml")
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def append_golden_set(path: Path | None, entries: list[dict],
                      want_new: int) -> tuple[Path, int]:
    """Keep every existing entry (labels intact); add up to want_new fresh ones."""
    path = path or (paths.HOME / "labels" / "golden_set.yaml")
    existing = load_existing(path)
    have_urls = {e.get("url") for e in existing}
    fresh = [e for e in entries if e.get("url") not in have_urls][:want_new]
    if fresh:
        write_golden_set(path, existing + fresh, overwrite=True)
    return path, len(fresh)


def write_golden_set(path: Path | None, entries: list[dict],
                     overwrite: bool = False) -> Path:
    path = path or (paths.HOME / "labels" / "golden_set.yaml")
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; re-run with --overwrite to replace")
    header = (
        "# Golden set: fill label: apply | inbox | discard on EVERY entry.\n"
        "#   apply   = you would be happy with the bot auto-applying here\n"
        "#   inbox   = a human should look at this first\n"
        "#   discard = ignore (below your bar)\n"
        "# Label by YOUR judgment, not system_score. Then run: jobagent eval\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(entries, f, allow_unicode=True, sort_keys=False, width=120)
    return path
