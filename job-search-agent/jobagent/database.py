"""SQLite store: jobs, scores, applications, ledger, LLM budget/cache, runs.

Durable ledger guarantees the pipeline never applies twice and never emails twice.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_job_id TEXT,
    canonical_url TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    title TEXT,
    company TEXT,
    company_url TEXT,
    location TEXT,
    remote_type TEXT,
    posted_at TEXT,
    discovered_at TEXT,
    apply_type TEXT,
    description_text TEXT,
    requirements TEXT,
    salary_raw TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    experience_min REAL,
    experience_max REAL,
    applicant_count INTEGER,
    raw_payload TEXT,
    first_seen_run TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    run_id TEXT,
    overall_match REAL,
    deterministic_score REAL,
    llm_score REAL,
    bucket TEXT,
    reasons TEXT,
    evidence TEXT,
    missing_facts TEXT,
    resume_used TEXT,
    scored_at TEXT,
    UNIQUE(job_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_job ON scores(job_id);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL,            -- applied | apply_failed | would_apply_dryrun | skipped
    platform TEXT,
    detail TEXT,
    resume_used TEXT,
    applied_at TEXT,
    UNIQUE(job_id, status)
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    event TEXT NOT NULL,             -- applied | emailed | discarded | inbox | rejected | blocklisted
    dedup_key TEXT,
    detail TEXT,
    created_at TEXT,
    run_id TEXT,
    UNIQUE(job_id, event)
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    response TEXT,
    model TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    calls INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    rate_limited INTEGER DEFAULT 0,
    UNIQUE(day, provider, model)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    phase TEXT,
    summary TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- jobs -------------------------------------------------------------
    def upsert_job(self, job: dict[str, Any], run_id: str = "") -> int:
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO jobs (source, source_job_id, canonical_url, dedup_key, title,
                    company, company_url, location, remote_type, posted_at, discovered_at,
                    apply_type, description_text, requirements, salary_raw, salary_min,
                    salary_max, salary_currency, experience_min, experience_max,
                    applicant_count, raw_payload, first_seen_run)
                VALUES (:source, :source_job_id, :canonical_url, :dedup_key, :title,
                    :company, :company_url, :location, :remote_type, :posted_at, :discovered_at,
                    :apply_type, :description_text, :requirements, :salary_raw, :salary_min,
                    :salary_max, :salary_currency, :experience_min, :experience_max,
                    :applicant_count, :raw_payload, :first_seen_run)
                ON CONFLICT(dedup_key) DO UPDATE SET
                    posted_at=COALESCE(excluded.posted_at, jobs.posted_at),
                    description_text=COALESCE(NULLIF(excluded.description_text,''), jobs.description_text),
                    apply_type=COALESCE(NULLIF(excluded.apply_type,''), jobs.apply_type),
                    salary_raw=COALESCE(NULLIF(excluded.salary_raw,''), jobs.salary_raw),
                    applicant_count=COALESCE(excluded.applicant_count, jobs.applicant_count)
                """,
                {
                    "source": job.get("source", ""),
                    "source_job_id": job.get("source_job_id", ""),
                    "canonical_url": job.get("canonical_url", ""),
                    "dedup_key": job["dedup_key"],
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "company_url": job.get("company_url", ""),
                    "location": job.get("location", ""),
                    "remote_type": job.get("remote_type", ""),
                    "posted_at": job.get("posted_at"),
                    "discovered_at": job.get("discovered_at") or _now(),
                    "apply_type": job.get("apply_type", "unknown"),
                    "description_text": job.get("description_text", ""),
                    "requirements": job.get("requirements", ""),
                    "salary_raw": job.get("salary_raw", ""),
                    "salary_min": job.get("salary_min"),
                    "salary_max": job.get("salary_max"),
                    "salary_currency": job.get("salary_currency", ""),
                    "experience_min": job.get("experience_min"),
                    "experience_max": job.get("experience_max"),
                    "applicant_count": job.get("applicant_count"),
                    "raw_payload": job.get("raw_payload", ""),
                    "first_seen_run": run_id,
                },
            )
            row = c.execute("SELECT id FROM jobs WHERE dedup_key=?", (job["dedup_key"],)).fetchone()
            return int(row["id"])

    def get_job(self, job_id: int) -> sqlite3.Row | None:
        with self._conn() as c:
            return c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def all_jobs(self) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT * FROM jobs ORDER BY posted_at DESC").fetchall()

    # ---- scores -----------------------------------------------------------
    def upsert_score(self, job_id: int, run_id: str, data: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO scores (job_id, run_id, overall_match, deterministic_score,
                    llm_score, bucket, reasons, evidence, missing_facts, resume_used, scored_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id, run_id) DO UPDATE SET
                    overall_match=excluded.overall_match, deterministic_score=excluded.deterministic_score,
                    llm_score=excluded.llm_score, bucket=excluded.bucket, reasons=excluded.reasons,
                    evidence=excluded.evidence, missing_facts=excluded.missing_facts,
                    resume_used=excluded.resume_used, scored_at=excluded.scored_at
                """,
                (
                    job_id, run_id, data.get("overall_match"), data.get("deterministic_score"),
                    data.get("llm_score"), data.get("bucket"),
                    json.dumps(data.get("reasons", [])),
                    json.dumps(data.get("evidence", [])),
                    json.dumps(data.get("missing_facts", [])),
                    data.get("resume_used", ""), _now(),
                ),
            )

    def scored_jobs(self, run_id: str | None = None) -> list[dict]:
        """Jobs + latest scores, newest-scored first. For golden-set building."""
        with self._conn() as c:
            if run_id is None:
                row = c.execute("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
                if row:
                    run_id = row["run_id"]
                else:
                    row = c.execute("SELECT run_id FROM scores ORDER BY ROWID DESC LIMIT 1").fetchone()
                    if not row:
                        return []
                    run_id = row["run_id"]
            rows = c.execute(
                """SELECT j.*, s.overall_match AS score, s.bucket AS bucket
                   FROM jobs j JOIN scores s ON s.job_id = j.id AND s.run_id = ?
                   ORDER BY s.overall_match DESC""", (run_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_score(self, job_id: int, run_id: str | None = None) -> sqlite3.Row | None:
        with self._conn() as c:
            if run_id:
                return c.execute("SELECT * FROM scores WHERE job_id=? AND run_id=?", (job_id, run_id)).fetchone()
            return c.execute("SELECT * FROM scores WHERE job_id=? ORDER BY scored_at DESC LIMIT 1", (job_id,)).fetchone()

    # ---- ledger (idempotency) --------------------------------------------
    def has_event(self, job_id: int, event: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT 1 FROM ledger WHERE job_id=? AND event=?", (job_id, event)).fetchone()
            return row is not None

    def record_event(self, job_id: int, event: str, detail: str, dedup_key: str = "", run_id: str = "") -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR IGNORE INTO ledger (job_id, event, dedup_key, detail, created_at, run_id)
                   VALUES (?,?,?,?,?,?)""",
                (job_id, event, dedup_key, detail, _now(), run_id),
            )

    # ---- applications -----------------------------------------------------
    def record_application(self, job_id: int, status: str, run_id: str, platform: str,
                           detail: str, resume_used: str = "") -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR IGNORE INTO applications (job_id, run_id, status, platform, detail,
                   resume_used, applied_at) VALUES (?,?,?,?,?,?,?)""",
                (job_id, run_id, status, platform, detail, resume_used, _now()),
            )

    def applied_today(self, platform: str, day_utc: str) -> int:
        with self._conn() as c:
            row = c.execute(
                """SELECT COUNT(*) AS n FROM applications
                   WHERE status='applied' AND platform=? AND applied_at LIKE ?""",
                (platform, f"{day_utc}%"),
            ).fetchone()
            return int(row["n"])

    # ---- llm --------------------------------------------------------------
    def cache_get(self, cache_key: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT response FROM llm_cache WHERE cache_key=?", (cache_key,)).fetchone()
            return row["response"] if row else None

    def cache_put(self, cache_key: str, response: str, model: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, response, model, created_at) VALUES (?,?,?,?)",
                (cache_key, response, model, _now()),
            )

    def usage_inc(self, day: str, provider: str, model: str, field: str = "calls") -> None:
        assert field in {"calls", "errors", "rate_limited"}
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO llm_usage (day, provider, model) VALUES (?,?,?)",
                (day, provider, model),
            )
            c.execute(f"UPDATE llm_usage SET {field}={field}+1 WHERE day=? AND provider=? AND model=?",
                      (day, provider, model))

    def usage_get(self, day: str, provider: str, model: str) -> int:
        with self._conn() as c:
            row = c.execute("SELECT calls FROM llm_usage WHERE day=? AND provider=? AND model=?",
                            (day, provider, model)).fetchone()
            return int(row["calls"]) if row else 0

    # ---- runs -------------------------------------------------------------
    def start_run(self, run_id: str, phase: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO runs (run_id, started_at, phase) VALUES (?,?,?)",
                      (run_id, _now(), phase))

    def finish_run(self, run_id: str, summary: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET finished_at=?, summary=? WHERE run_id=?",
                      (_now(), json.dumps(summary), run_id))