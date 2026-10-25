from jobagent.models import Job


def test_dedup_across_platforms_same_company_title_city():
    li = Job(source="linkedin", company="Acme India Pvt Ltd", title="Senior Backend Engineer",
             location="Bengaluru, Karnataka", canonical_url="https://linkedin.com/jobs/view/1")
    nk = Job(source="naukri", company="Acme India Pvt Ltd", title="Backend Engineer",
             location="Bengaluru", canonical_url="https://naukri.com/job-listings-1")
    assert li.dedup_key == nk.dedup_key


def test_different_city_not_deduped():
    a = Job(source="linkedin", company="Acme", title="Backend Engineer", location="Bengaluru")
    b = Job(source="naukri", company="Acme", title="Backend Engineer", location="Pune")
    assert a.dedup_key != b.dedup_key


def test_dedup_key_stable():
    a = Job(source="linkedin", company="Acme", title="Backend Engineer", location="Bengaluru")
    b = Job(source="linkedin", company="Acme", title="Backend Engineer", location="Bengaluru")
    assert a.dedup_key == b.dedup_key