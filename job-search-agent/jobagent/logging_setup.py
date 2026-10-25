"""Structured logging with secret scrubbing. Never logs keys, passwords, or PII."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from . import paths

_SECRET_PATTERNS = [
    re.compile(r"(nvapi-[A-Za-z0-9_\-]{6,})"),
    re.compile(r"(sk-[A-Za-z0-9_\-]{10,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.]{10,})", re.IGNORECASE),
    re.compile(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"),
]

_REDACTED = "***REDACTED***"


def scrub(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub(_REDACTED, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO, log_dir=None) -> logging.Logger:
    log_dir = log_dir or paths.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jobagent")
    logger.setLevel(level)
    logger.handlers.clear()

    fh = logging.FileHandler(log_dir / "jobagent.log", encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(sh)
    return logger


def get_logger(name: str = "jobagent") -> logging.Logger:
    return logging.getLogger(name)