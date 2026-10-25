"""Domain models for jobs and the normalized job record."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .textutil import normalize_ws, parse_salary, parse_relative_date


@dataclass
class Job:
    source: str = ""                 # linkedin | naukri | email
    source_job_id: str = ""
    canonical_url: str = ""
    title: str = ""
    company: str = ""
    company_url: str = ""
    location: str = ""
    remote_type: str = ""            # remote | hybrid | onsite | ""
    posted_at: str | None = None     # ISO UTC
    discovered_at: str | None = None
    apply_type: str = "unknown"      # easy_apply | naukri_apply | external_ats | unknown
    description_text: str = ""
    requirements: str = ""
    salary_raw: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    experience_min: float | None = None
    experience_max: float | None = None
    applicant_count: int | None = None
    raw_payload: str = ""
    dedup_key: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.title = normalize_ws(self.title)
        self.company = normalize_ws(self.company)
        self.location = normalize_ws(self.location)
        if self.posted_at is None:
            self.posted_at = None
        if self.discovered_at is None:
            self.discovered_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.salary_currency and self.salary_raw:
            lo, hi, cur = parse_salary(self.salary_raw)
            self.salary_min, self.salary_max = lo, hi
            self.salary_currency = cur
        self.dedup_key = self.compute_dedup_key()

    def compute_dedup_key(self) -> str:
        """Stable across platforms: company + normalized title + normalized city."""
        company = re.sub(r"[^a-z0-9]", "", self.company.lower())
        # strip seniority noise from titles
        title = self.title.lower()
        for noise in ("senior", "sr.", "sr", "junior", "jr.", "jr", "lead", "staff",
                      "principal", "i", "ii", "iii"):
            title = re.sub(rf"\b{re.escape(noise)}\b", " ", title)
        title = re.sub(r"[^a-z0-9]", "", title)
        city = self.location.lower().split(",")[0]
        city = re.sub(r"[^a-z0-9]", "", city)
        basis = f"{company}|{title}|{city}"
        if not company and not title:
            basis = self.canonical_url
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    def to_db(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("dedup_key", None)
        d["dedup_key"] = self.dedup_key
        if not d.get("discovered_at"):
            d["discovered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return d

    def age_hours(self, now: datetime | None = None) -> float | None:
        if not self.posted_at:
            return None
        now = now or datetime.now(timezone.utc)
        try:
            posted = datetime.fromisoformat(self.posted_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        return (now - posted).total_seconds() / 3600.0


def job_from_row(row: Any) -> Job:
    return Job(
        source=row["source"], source_job_id=row["source_job_id"] or "",
        canonical_url=row["canonical_url"], title=row["title"] or "",
        company=row["company"] or "", company_url=row["company_url"] or "",
        location=row["location"] or "", remote_type=row["remote_type"] or "",
        posted_at=row["posted_at"], discovered_at=row["discovered_at"],
        apply_type=row["apply_type"] or "unknown",
        description_text=row["description_text"] or "",
        requirements=row["requirements"] or "", salary_raw=row["salary_raw"] or "",
        salary_min=row["salary_min"], salary_max=row["salary_max"],
        salary_currency=row["salary_currency"] or "",
        experience_min=row["experience_min"], experience_max=row["experience_max"],
        applicant_count=row["applicant_count"], raw_payload=row["raw_payload"] or "",
    )


def normalize_posted(raw: str) -> str | None:
    """Convert '2 hours ago', 'Reposted 3 days ago', '2026-09-20' to ISO UTC."""
    return parse_relative_date(raw)