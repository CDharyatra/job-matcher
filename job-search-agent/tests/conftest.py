import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from jobagent.config import (
    ApplyConfig, BrowserConfig, Config, EmailConfig, LLMConfig, LLMModel,
    RoutingConfig, SearchConfig, StorageConfig,
)
from jobagent.database import Store
from jobagent.facts import Facts


@pytest.fixture
def cfg(tmp_path):
    return Config(
        search=SearchConfig(
            target_titles=["Senior Backend Engineer"],
            must_have_skills=["Python", "PostgreSQL", "AWS"],
            nice_to_have_skills=["Docker", "Kubernetes"],
            negative_keywords=["wordpress", "intern"],
            locations=["Bengaluru", "Hyderabad"],
            remote_ok=True,
            min_results_before_widening=1,
            max_pages_per_query=1,
        ),
        routing=RoutingConfig(discard_below=70, inbox_above=90),
        apply=ApplyConfig(live_submit_enabled=False, daily_auto_apply_cap_per_platform=5),
        email=EmailConfig(),
        browser=BrowserConfig(user_data_dir=str(tmp_path / "prof")),
        llm=LLMConfig(
            enabled=True,
            judge_chain=[LLMModel("nvidia", "deepseek-ai/deepseek-v4.1-flash")],
            classify_chain=[LLMModel("nvidia", "z-ai/glm-5.3-flash")],
        ),
        storage=StorageConfig(sqlite_path=str(tmp_path / "test.sqlite3")),
        platforms={"linkedin": {"enabled": True}, "naukri": {"enabled": True}},
        blocklist={"companies": ["BadCorp"], "keywords": ["ghost posting"]},
    )


@pytest.fixture
def facts():
    return Facts(data={
        "identity": {
            "full_name": "Test User", "email": "test@example.com", "phone": "9876543210",
            "current_city": "Bengaluru", "relocate_cities": ["Hyderabad", "Pune"],
            "willing_to_relocate": "yes",
        },
        "compensation": {
            "current_ctc": "18", "expected_ctc": "28", "expected_ctc_floor": "24",
            "expected_ctc_unit": "LPA", "notice_period_days": "60",
            "current_company": "Acme Corp",
        },
        "experience": {"total_years": "6", "relevant_years": "5", "work_authorization_india": "yes"},
        "application": {"resume_files": [{"path": "", "label": "default"}], "default_resume": "default"},
        "screening_answers": {"reason_for_job_change": "Looking for growth"},
    })


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "s.sqlite3")