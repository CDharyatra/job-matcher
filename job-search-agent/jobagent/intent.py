"""Build search queries from config + resume: titles, synonyms, skills, negatives."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .resume import ResumeProfile
from .textutil import canonical_city, expand_title


@dataclass
class SearchQuery:
    title: str
    keywords: str
    location: str = ""
    experience_min: str = ""
    experience_max: str = ""
    remote: bool = False


def build_queries(cfg: Config, profile: ResumeProfile | None = None) -> list[SearchQuery]:
    titles: list[str] = list(cfg.search.target_titles or [])
    if not titles and profile:
        titles = profile.titles[:3]
    expanded: list[str] = []
    for t in titles:
        expanded += expand_title(t)
    # keep order, drop dupes/empties
    seen: set[str] = set()
    uniq = []
    for t in expanded:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)

    # Dedupe spelling variants (Bengaluru/Bangalore return the same results).
    locations: list[str] = []
    for loc in cfg.search.locations or [""]:
        if canonical_city(loc) not in {canonical_city(l) for l in locations}:
            locations.append(loc)
    queries: list[SearchQuery] = []
    for t in uniq[:8]:  # cap query fan-out
        skills_tail = " ".join((cfg.search.must_have_skills or [])[:3])
        kw = t if not skills_tail else f"{t} {skills_tail}"
        for loc in locations:
            queries.append(SearchQuery(
                title=t, keywords=kw, location=loc,
                experience_min=str(cfg.search.experience_min or ""),
                experience_max=str(cfg.search.experience_max or ""),
                remote=cfg.search.remote_ok,
            ))
    if cfg.search.remote_ok and not any(q.location.lower() == "remote" for q in queries):
        queries.append(SearchQuery(title=uniq[0] if uniq else "", keywords=(uniq[0] if uniq else ""), location="remote", remote=True))
    return queries