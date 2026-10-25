import re
from pathlib import Path

from jobagent.llm.paid_blocklist import PAID_MODELS, PAID_SERVICE_NAMES
from jobagent.logging_setup import scrub

REPO = Path(__file__).resolve().parent.parent


def test_paid_apis_not_referenced_in_source():
    """Grep the repo for banned paid services. Docs may mention them; code may not."""
    banned = ["sendgrid", "mailgun", "postmark", "linked helper", "resumly",
              "2captcha", "anticaptcha", "brightdata", "bright data", "scraperapi"]
    offenders = []
    for p in REPO.rglob("*.py"):
        if ".venv" in p.parts or "jobagent.egg-info" in p.parts:
            continue
        if p.name in {"paid_blocklist.py", "test_security.py"}:
            continue
        low = p.read_text(encoding="utf-8", errors="ignore").lower()
        for b in banned:
            if b in low:
                offenders.append(f"{p.name}: {b}")
    assert not offenders, offenders


def test_log_scrubber_removes_secrets_and_email():
    s = scrub("key nvapi-abcdef123456 token Bearer sk-ABCDEFGH12345 mail a@b.com")
    assert "nvapi-" not in s
    assert "sk-ABCDEFGH" not in s
    assert "a@b.com" not in s


def test_no_hardcoded_keys_in_repo():
    patterns = [re.compile(r"nvapi-[A-Za-z0-9]{20,}"), re.compile(r"sk-[A-Za-z0-9]{30,}")]
    offenders = []
    for p in REPO.rglob("*"):
        if p.is_dir() or ".venv" in p.parts or ".git" in p.parts or "egg-info" in p.parts:
            continue
        if p.suffix in {".pyc", ".sqlite3", ".pdf", ".docx", ".png"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for pat in patterns:
            if pat.search(text):
                offenders.append(str(p.relative_to(REPO)))
    assert not offenders, offenders


def test_env_and_facts_are_gitignored():
    gi = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi
    assert "candidate_facts.yaml" in gi


def test_blocklist_contains_expected_services():
    for svc in ("sendgrid", "mailgun", "postmark"):
        assert svc in PAID_SERVICE_NAMES
    assert "kimi-k3" in PAID_MODELS