"""ATS collector mapping/filters (no network — fixture payloads only)."""

from jobagent.ats import (
    DEFAULT_COMPANIES,
    _boards,
    _in_scope,
    _iso,
    _map_item,
    _normalize_location,
    _strip_html,
    _title_relevant,
)


def _gh_item(**kw):
    base = {
        "id": 4241380009,
        "title": "Machine Learning Engineer - L3",
        "location": {"name": "Bengaluru"},
        "absolute_url": "https://job-boards.greenhouse.io/rzr/jobs/4241380009",
        "company_name": "RZR",
        "first_published": "2026-10-10T09:00:00-04:00",
    }
    base.update(kw)
    return base


def test_greenhouse_maps_to_external_job():
    job = _map_item("greenhouse", "rzr", "RZR", _gh_item())
    assert job is not None
    assert job.source == "ats"
    assert job.apply_type == "external_ats"
    assert job.title == "Machine Learning Engineer - L3"
    assert job.company == "RZR"
    assert job.location == "Bengaluru"
    assert job.canonical_url.startswith("https://job-boards.greenhouse.io/")
    assert job.posted_at and job.posted_at.startswith("2026-10-10")
    assert job.source_job_id == "greenhouse:rzr:4241380009"


def test_lever_bangalore_in_title_repairs_location():
    item = {
        "id": "abc-123", "text": "Senior Machine Learning Engineer (Bangalore/Noida Location)",
        "categories": {"location": "Noida"},
        "hostedUrl": "https://jobs.lever.co/levelai/abc-123",
        "createdAt": 1791500000000,
    }
    job = _map_item("lever", "levelai", "Level AI", item)
    assert job is not None
    assert "Bengaluru" in job.location
    assert _in_scope(job.location)


def test_lever_single_city_outside_scope_dropped():
    item = {
        "id": "xyz", "text": "Senior Machine Learning Engineer",
        "categories": {"location": "Noida"},
        "hostedUrl": "https://jobs.lever.co/levelai/xyz",
        "createdAt": 1791500000000,
    }
    assert _map_item("lever", "levelai", "Level AI", item) is None


def test_ashby_maps():
    item = {
        "id": "2aae524c", "title": "Machine Learning Engineer",
        "location": "Bengaluru",
        "jobUrl": "https://jobs.ashbyhq.com/spector-ai/2aae524c",
        "publishedAt": "2026-10-09T12:00:00.000Z",
        "descriptionPlain": "Build ML models with Python and PyTorch in Bengaluru.",
    }
    job = _map_item("ashby", "spector-ai", "Spector.ai", item)
    assert job is not None
    assert (job.company, job.location) == ("Spector.ai", "Bengaluru")
    assert "Python" in job.description_text
    assert "<" not in job.description_text


def test_irrelevant_title_dropped():
    assert _map_item("greenhouse", "rzr", "RZR",
                     _gh_item(title="Sales Manager")) is None


def test_missing_title_or_url_dropped():
    assert _map_item("greenhouse", "rzr", "RZR", _gh_item(title="")) is None
    assert _map_item("greenhouse", "rzr", "RZR", _gh_item(absolute_url="")) is None


def test_title_relevance():
    assert _title_relevant("Software Engineer, Backend")
    assert _title_relevant("Senior Machine Learning Engineer (GenAI)")
    assert not _title_relevant("Technical Recruiter")
    assert not _title_relevant("Account Executive")


def test_location_scope():
    assert _in_scope("Bengaluru")
    assert _in_scope("Bengaluru, Hyderabad, Delhi NCR")
    assert _in_scope("Remote - India")
    assert _in_scope("")
    assert not _in_scope("Noida")
    assert not _in_scope("Hyderabad")


def test_normalize_location_appends_bangalore():
    assert _normalize_location("ML Engineer (Bangalore/Noida)", "Noida") == "Noida / Bengaluru"
    assert _normalize_location("ML Engineer", "Bengaluru") == "Bengaluru"


def test_iso_parses_epoch_ms_and_iso():
    assert _iso(1791500000000).startswith("2026-10-")
    assert _iso("2026-10-10T09:00:00-04:00").startswith("2026-10-10")
    assert _iso("") is None
    assert _iso(None) is None


def test_strip_html():
    assert _strip_html("<p>Hello <b>World</b></p>") == "Hello World"


def test_strip_html_unescapes_first():
    # Greenhouse ships HTML-escaped content; tags must not survive.
    assert _strip_html("&lt;p&gt;Hello&lt;/p&gt;") == "Hello"
    assert _strip_html("R&amp;D") == "R&D"


def test_lever_detail_handles_string_content(monkeypatch):
    import jobagent.ats as ats_mod
    payload = {
        "description": "<p>ML role</p>",
        "lists": [{"text": "Requirements", "content": "<li>Python and PyTorch</li>"}],
    }
    monkeypatch.setattr(ats_mod, "_get_json", lambda url: payload)
    text = ats_mod._lever_detail("levelai", "abc")
    assert "Python" in text
    assert "<" not in text


class _Cfg:
    def __init__(self, companies):
        self.platforms = {"ats": {"companies": companies}}


def test_empty_companies_falls_back_to_defaults():
    assert _boards(_Cfg([])) == DEFAULT_COMPANIES
    assert _boards(_Cfg(None)) == DEFAULT_COMPANIES


def test_custom_companies_used_as_is():
    custom = [{"provider": "lever", "board": "x", "company": "X"}]
    assert _boards(_Cfg(custom)) == custom
