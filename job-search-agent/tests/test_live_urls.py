"""Ground-truth URL handling, from real links observed in the user's browser."""

from jobagent.browser import linkedin as li
from jobagent.browser import naukri as nk


class FakeEl:
    def __init__(self, text="", attrs=None):
        self._text = text
        self._attrs = attrs or {}

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._attrs.get(name)


class FakeCard:
    def __init__(self, mapping):
        self._mapping = mapping

    def query_selector(self, selector):
        for key, el in self._mapping.items():
            if key in selector:
                return el
        return None


class FakeQuery:
    keywords = "machine learning"
    location = "Bengaluru"
    remote = False


def _li_card(href):
    return FakeCard({
        "job-card-container__link": FakeEl("ML Engineer", {"href": href}),
        "primary-description": FakeEl("Acme"),
    })


def test_linkedin_current_job_id_canonicalized():
    href = ("/jobs/search-results/?currentJobId=4472707472&keywords=machine%20learning"
            "&origin=JOB_SEARCH_PAGE_JOB_FILTER&f_TPR=r86400")
    job = li._job_from_card(_li_card(href), FakeQuery(), None)
    assert job is not None
    assert job.source_job_id == "4472707472"
    assert job.canonical_url == "https://www.linkedin.com/jobs/view/4472707472/"


def test_linkedin_classic_view_url():
    job = li._job_from_card(_li_card("/jobs/view/12345?trk=email"), FakeQuery(), None)
    assert job.source_job_id == "12345"
    assert job.canonical_url == "https://www.linkedin.com/jobs/view/12345/"


class FakeSearchPage:
    def __init__(self, items):
        self._items = items

    def eval_on_selector_all(self, _selector, _expr):
        return self._items


def test_harvest_ids_from_anchors():
    from jobagent.browser.linkedin import _harvest_ids
    page = FakeSearchPage([
        {"href": "/jobs/search-results/?currentJobId=4472707472&keywords=x", "text": "ML Engineer\nBengaluru"},
        {"href": "/jobs/search-results/?currentJobId=4472707472&keywords=x", "text": "dupe"},
        {"href": "/jobs/search-results/?keywords=x", "text": "no id"},
    ])
    out = _harvest_ids(page)
    assert out == [("4472707472", "ML Engineer\nBengaluru")]


def test_harvest_ids_empty_on_error():
    from jobagent.browser.linkedin import _harvest_ids

    class Boom:
        def eval_on_selector_all(self, _s, _e):
            raise RuntimeError("nope")

    assert _harvest_ids(Boom()) == []


def test_junk_anchor_text_skipped():
    from jobagent.browser.linkedin import _ids_from_items
    out = _ids_from_items([
        {"href": "/jobs/search-results/?currentJobId=111", "text": "More"},
        {"href": "/jobs/search-results/?currentJobId=222", "text": "ML Engineer"},
        {"href": "/jobs/search-results/?currentJobId=333", "text": ""},
        {"href": "/jobs/search-results/?currentJobId=444", "text": "Hybrid"},
        {"href": "/jobs/search-results/?currentJobId=555", "text": "Remote"},
    ])
    assert [jid for jid, _ in out] == ["222", "333"]
    # but real titles merely CONTAINING those words survive
    out2 = _ids_from_items([
        {"href": "/jobs/search-results/?currentJobId=666", "text": "Hybrid Cloud Engineer"},
    ])
    assert [jid for jid, _ in out2] == ["666"]


def test_enrich_from_text_fills_gaps():
    from jobagent.browser.linkedin import enrich_from_text
    from jobagent.models import Job
    job = Job(source="linkedin",
              canonical_url="https://www.linkedin.com/jobs/view/4470855383/")
    enrich_from_text(
        job,
        "AI/ML Engineer (Applied Machine Learning) | Voyantt Consultancy Services | LinkedIn",
        "Coinbase\nBengaluru (Remote)\nIndia 3 hours ago Over 100 applicants",
    )
    assert job.title.startswith("AI/ML Engineer")
    assert job.company == "Voyantt Consultancy Services"
    assert job.location == "Bengaluru"
    assert job.remote_type == "remote"
    assert job.posted_at is not None
    assert job.applicant_count == 100


def test_enrich_from_text_never_overwrites():
    from jobagent.browser.linkedin import enrich_from_text
    from jobagent.models import Job
    job = Job(source="linkedin", title="Real Title", company="Real Co",
              location="Pune", posted_at="2026-09-28T08:00:00+00:00",
              canonical_url="https://www.linkedin.com/jobs/view/1/")
    enrich_from_text(job, "Other Title | Other Co | LinkedIn",
                     "Bengaluru (Remote) 5 hours ago 10 applicants")
    assert (job.title, job.company, job.location) == ("Real Title", "Real Co", "Pune")
    assert job.posted_at == "2026-09-28T08:00:00+00:00"


class FakeApplyPage:
    def __init__(self, present):
        self._present = set(present)
        self.waited = False

    def query_selector(self, selector):
        return object() if selector in self._present else None


def test_linkedin_find_control_waits_first(monkeypatch):
    from jobagent.browser import linkedin as li

    def fake_wait(page, selectors, timeout_ms=0):
        page.waited = True
        return None

    monkeypatch.setattr(li, "wait_for_any_selector", fake_wait)
    page = FakeApplyPage({li.S.LINKEDIN["easy_apply_button"]})
    assert li._find_apply_control(page) == "easy"
    assert page.waited


def test_linkedin_find_control_external_and_none(monkeypatch):
    from jobagent.browser import linkedin as li
    monkeypatch.setattr(li, "wait_for_any_selector", lambda *a, **k: None)
    assert li._find_apply_control(
        FakeApplyPage({li.S.LINKEDIN["external_apply_link"]})) == "external"
    assert li._find_apply_control(FakeApplyPage(set())) == "none"


def test_naukri_find_control(monkeypatch):
    from jobagent.browser import naukri as nk
    monkeypatch.setattr(nk, "wait_for_any_selector", lambda *a, **k: None)
    assert nk._find_apply_control(
        FakeApplyPage({nk.S.NAUKRI["company_site_apply"]})) == "external"
    assert nk._find_apply_control(
        FakeApplyPage({nk.S.NAUKRI["in_platform_apply"]})) == "apply"
    assert nk._find_apply_control(FakeApplyPage(set())) == "none"


def test_naukri_already_applied_wins(monkeypatch):
    from jobagent.browser import naukri as nk
    monkeypatch.setattr(nk, "wait_for_any_selector", lambda *a, **k: None)
    # badge present alongside (stale) button markup -> still "applied"
    assert nk._find_apply_control(FakeApplyPage(
        {nk.S.NAUKRI["already_applied"],
         nk.S.NAUKRI["in_platform_apply"]})) == "applied"


def test_ids_from_content_shell():
    from jobagent.browser.linkedin import _ids_from_content
    html = ('{"componentKey":"job-card-component-ref-4470855383"}'
            'url":"/jobs/search-results/?currentJobId=4472707472\\u0026x=1"')
    assert _ids_from_content(html) == ["4470855383", "4472707472"]


def test_detail_selectors_use_stable_hooks():
    # Regression: hashed CSS-module classes and tag-specific #ids both failed
    # on live pages. Selectors must use data-testid / [class*=] / bare #id.
    from jobagent.browser import selectors as S
    assert "[data-testid='expandable-text-box']" in S.LINKEDIN["detail_description"]
    assert "[class*='dang-inner-html']" in S.NAUKRI["detail_description"]
    assert S.NAUKRI["company_site_apply"] == "#company-site-button"
    assert S.NAUKRI["in_platform_apply"] == "#apply-button"


def test_linkedin_search_base_is_results_page():
    assert li.BASE == "https://www.linkedin.com/jobs/search-results/"
    url = li.build_url("machine learning", "", 24)
    assert "search-results" in url
    assert "f_TPR=r86400" in url
    assert "keywords=machine+learning" in url or "keywords=machine%20learning" in url


USER_NAUKRI_URLS = [
    ("https://www.naukri.com/job-listings-data-scientist-valuelabs-mumbai-all-areas-4-to-9-years-270926003553?src=sortby&sid=17905889603971727_2&xp=1&px=1&nignbevent_src=jobsearchDeskGNB",
     "270926003553", 4.0, 9.0),
    ("https://www.naukri.com/job-listings-generative-ai-engineer-n-infosys-noida-pune-bengaluru-5-to-7-years-230926006807?src=sortby&sid=17905889603971727_2&xp=2&px=1&nignbevent_src=jobsearchDeskGNB",
     "230926006807", 5.0, 7.0),
    ("https://www.naukri.com/job-listings-gen-ai-infosys-hyderabad-bengaluru-mumbai-all-areas-2-to-7-years-220926048634?src=sortby&sid=17905889603971727_2&xp=3&px=1&nignbevent_src=jobsearchDeskGNB",
     "220926048634", 2.0, 7.0),
    ("https://www.naukri.com/job-listings-senior-data-scientist-cyient-hyderabad-7-to-12-years-280926007971",
     "280926007971", 7.0, 12.0),
]


def _nk_card(href):
    return FakeCard({
        "a.title": FakeEl("Data Scientist", {"href": href}),
    })


def test_naukri_job_ids_from_user_links():
    for href, jid, _lo, _hi in USER_NAUKRI_URLS:
        job = nk._job_from_card(_nk_card(href))
        assert job is not None, href
        assert job.source_job_id == jid, href


def test_naukri_experience_band_from_url():
    for href, _jid, lo, hi in USER_NAUKRI_URLS:
        job = nk._job_from_card(_nk_card(href))
        assert (job.experience_min, job.experience_max) == (lo, hi), href