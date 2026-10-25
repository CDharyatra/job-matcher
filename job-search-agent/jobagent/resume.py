"""Resume ingest: PDF + DOCX (including two-column layouts), profile JSON build.

Deterministic extraction only; an optional LLM structurer runs once and is cached.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .logging_setup import get_logger
from .paths import CACHE_DIR
from .textutil import normalize_ws, parse_years, skill_present, text_hash

log = get_logger("jobagent.resume")

# Bump whenever extraction logic or _SKILL_VOCAB changes, so cached profiles
# can never silently go stale across code updates.
PROFILE_CACHE_VERSION = "v2"

_SKILL_VOCAB = [
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#",
    "ruby", "php", "scala", "kotlin", "swift", "r",
    "fastapi", "django", "flask", "spring", "spring boot", "express", "nestjs", "rails",
    "react", "angular", "vue", "next.js", "svelte", "node.js",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "cassandra", "dynamodb",
    "sqlite", "oracle", "sql server",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible", "jenkins",
    "github actions", "gitlab ci", "ci/cd", "kafka", "rabbitmq", "celery", "airflow",
    "spark", "hadoop", "hive", "pyspark", "dbt", "snowflake", "databricks",
    "rest api", "graphql", "grpc", "microservices", "linux", "git",
    "machine learning", "deep learning", "nlp", "pytorch", "tensorflow", "scikit-learn",
    "xgboost", "pandas", "numpy", "opencv",
    "rag", "langchain", "langgraph", "prompt engineering", "text-to-sql",
    "semantic search", "vector embeddings", "conversational ai", "bedrock", "ollama",
    "transformers", "hugging face", "llm", "generative ai",
    "pgvector", "faiss", "opensearch", "openai",
    "sql", "streamlit", "typer", "jwt", "rbac", "websocket", "webhook", "pydantic",
    "plotly", "pytest",
]


@dataclass
class ResumeProfile:
    raw_text: str = ""
    headline: str = ""
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    total_years: float | None = None
    education: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)

    def deidentified_blob(self) -> str:
        """Skills + titles + date-banded bullets only. Safe-ish for redaction pass."""
        parts = [self.headline, self.summary]
        parts += self.skills
        parts += self.titles
        parts += self.bullets
        return "\n".join(p for p in parts if p)


def extract_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber not installed")
        return ""
    out: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            # sort by position to keep two-column text readable
            text = page.extract_text() or ""
            if not text.strip():
                words = page.extract_words()
                words.sort(key=lambda w: (round(w["top"] / 6), w["x0"]))
                text = " ".join(w["text"] for w in words)
            out.append(text)
    return "\n".join(out)


def extract_docx(path: Path) -> str:
    try:
        import docx
    except ImportError:
        log.error("python-docx not installed")
        return ""
    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def extract_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix in {".docx", ".doc"}:
        return extract_docx(path)
    return ""


def _detect_years(text: str) -> float | None:
    m = re.search(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*years?(?:\s+of)?\s+experience", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    lo, _ = parse_years(text)
    return lo


def build_profile(paths_list: list[str]) -> ResumeProfile:
    parts: list[str] = []
    files: list[str] = []
    for p in paths_list:
        if not p:
            continue
        fp = Path(p)
        if fp.exists():
            parts.append(extract_text(fp))
            files.append(str(fp))
    raw = normalize_ws("\n".join(parts))
    # preserve line structure for bullets separately
    lines = [normalize_ws(l) for l in "\n".join(parts).splitlines() if normalize_ws(l)]

    skills = sorted({s for s in _SKILL_VOCAB if skill_present(s, raw.lower())})
    bullets = [l for l in lines if len(l) > 25 and (l.startswith(("-", "\u2022", "*")) or re.match(r"^[A-Z].*[.;]$", l))][:60]
    titles: list[str] = []
    for line in lines[:80]:
        for t in ("engineer", "developer", "architect", "manager", "analyst", "scientist", "lead", "consultant"):
            if t in line.lower() and len(line) < 80:
                titles.append(line)
                break
    companies = re.findall(r"(?:at|@)\s+([A-Z][A-Za-z0-9&.\- ]{2,40})", raw)

    profile = ResumeProfile(
        raw_text=raw,
        headline=lines[0] if lines else "",
        summary=" ".join(lines[:3]),
        skills=skills,
        titles=sorted(set(titles))[:10],
        total_years=_detect_years(raw),
        bullets=bullets,
        companies=sorted(set(c.strip() for c in companies))[:10],
        files=files,
    )
    return profile


def load_or_build(paths_list: list[str]) -> ResumeProfile:
    """Cache profile JSON keyed by file content hash."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    file_hashes = []
    for p in paths_list:
        fp = Path(p)
        if fp.exists():
            file_hashes.append(text_hash(fp.name, str(fp.stat().st_mtime_ns)))
    key = text_hash(PROFILE_CACHE_VERSION, *file_hashes)[:24] if file_hashes else "empty"
    cache_file = CACHE_DIR / f"resume_profile_{key}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return ResumeProfile(**data)
    profile = build_profile(paths_list)
    cache_file.write_text(profile.to_json(), encoding="utf-8")
    return profile