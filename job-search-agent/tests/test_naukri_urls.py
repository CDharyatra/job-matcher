from jobagent.browser.naukri import build_url, build_urls


def test_primary_shape_mirrors_site_search_links():
    urls = build_urls("machine learning, python", "Bengaluru", 1)
    first = urls[0]
    assert "k=machine%20learning%2C%20python" in first
    assert "jobAge=1" in first
    assert "sort=" not in first
    assert "-jobs-in-bengaluru" in first


def test_fallback_shape_matches_user_proven_url():
    urls = build_urls("machine learning, python", "Bengaluru", 1)
    assert urls[1] == ("https://www.naukri.com/machine-learning%2C-python-jobs"
                       "?k=machine%20learning%2C%20python&jobAge=1")


def test_pagination_appended_to_all_shapes():
    urls = build_urls("python", "Bengaluru", 1, page=2)
    assert urls and all("pageNo=2" in u for u in urls)


def test_build_url_returns_primary_shape():
    assert build_url("python", "Bengaluru", 1) == build_urls("python", "Bengaluru", 1)[0]


def test_no_location_still_builds():
    urls = build_urls("python", "", 3)
    assert urls and all("jobAge=3" in u for u in urls)


def test_only_relevance_shapes_no_forced_sort():
    urls = build_urls("machine learning, python", "Bengaluru", 1)
    assert len(urls) == 2
    assert all("sort=" not in u for u in urls)


def test_freshness_defaults_to_one_day(cfg):
    from jobagent.browser.naukri import _freshness_days
    assert _freshness_days(cfg) == [1]


def test_freshness_configured_ladder():
    from jobagent.browser.naukri import _freshness_days

    class Cfg:
        platforms = {"naukri": {"freshness_days": [1, 3]}}

    assert _freshness_days(Cfg()) == [1, 3]