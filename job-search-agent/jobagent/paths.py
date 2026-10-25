"""Project paths. Resolves everything relative to an optional JOBAGENT_HOME."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("JOBAGENT_HOME", PROJECT_ROOT)).resolve()

CONFIG_PATH = HOME / "config.yaml"
FACTS_PATH = HOME / "candidate_facts.yaml"
ENV_PATH = HOME / ".env"
DOCS_DIR = HOME / "docs"
RESUMES_DIR = HOME / "resumes"
DATA_DIR = HOME / "data"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "jobagent.sqlite3"
BROWSER_DIR = HOME / ".browser"


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, LOG_DIR, RESUMES_DIR, DOCS_DIR):
        d.mkdir(parents=True, exist_ok=True)