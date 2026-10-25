"""Naukri card parsing against the live markup observed 2026-09-28."""

from jobagent.browser.naukri import _job_from_card


class El:
    def __init__(self, text="", attrs=None):
        self._text = text
        self._attrs = attrs or {}

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._attrs.get(name)


class LiveCard:
    """Mirrors the observed live structure (row1..row6, title attrs, tags)."""

    def query_selector(self, selector):
        if selector.startswith("a.title"):
            return El("", {"href": "https://www.naukri.com/job-listings-x-040926021073",
                           "title": "Lead/Senior Domino Data Lab with Python"})
        if "comp-name" in selector:
            return El("Epam", {"title": "Epam Systems"})
        if "locWdth" in selector or selector == ".location":
            return El("Bengaluru, Hyderabad, Chennai")
        if "job-post-day" in selector:
            return El("1 day ago")
        if "expwdth" in selector or selector == ".experience":
            return El("8-12 Yrs")
        if selector == "span.job-desc":
            return El("5-14 years of professional software experience.")
        return None

    def query_selector_all(self, selector):
        if "tag-li" in selector:
            return [El("Python"), El("Machine Learning"), El("")]
        return []

    def get_attribute(self, name):
        return "040926021073" if name == "data-job-id" else None


def test_live_card_fields():
    job = _job_from_card(LiveCard())
    assert job is not None
    assert job.title == "Lead/Senior Domino Data Lab with Python"
    assert job.company == "Epam Systems"
    assert job.location == "Bengaluru, Hyderabad, Chennai"
    assert job.source_job_id == "040926021073"  # data-job-id, leading zero kept
    assert (job.experience_min, job.experience_max) == (8.0, 12.0)
    assert "Python" in job.requirements and "Machine Learning" in job.requirements
    assert job.description_text != ""  # card snippet captured


def test_merge_detail_never_wipes_card_data():
    from jobagent.browser.linkedin import merge_detail
    from jobagent.models import Job
    job = Job(source="naukri", title="X", company="Y",
              description_text="card snippet here", salary_raw="10 LPA")
    merge_detail(job, {"description_text": "", "salary_raw": "",
                       "posted_raw": "", "applicants_raw": ""})
    assert job.description_text == "card snippet here"
    assert job.salary_raw == "10 LPA"


def test_merge_detail_upgrades():
    from jobagent.browser.linkedin import merge_detail
    from jobagent.models import Job
    job = Job(source="linkedin", title="X", description_text="short")
    merge_detail(job, {"description_text": "full description. " * 20,
                       "salary_raw": "30-40 LPA", "posted_raw": "",
                       "applicants_raw": "51 applicants"})
    assert job.description_text.startswith("full description")
    assert job.salary_min == 3000000.0
    assert job.applicant_count == 51