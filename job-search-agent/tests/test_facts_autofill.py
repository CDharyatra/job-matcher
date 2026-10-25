from jobagent.autofill import Autofill
from jobagent.facts import Facts


def test_maps_current_ctc(facts):
    value, key = facts.answer_for_question("What is your current CTC?")
    assert value == "18"
    assert key == "compensation.current_ctc"


def test_maps_notice_period(facts):
    value, key = facts.answer_for_question("Notice period (in days)")
    assert value == "60"


def test_maps_expected_ctc(facts):
    value, key = facts.answer_for_question("Expected CTC")
    assert value == "28"


def test_maps_bare_ctc_to_current(facts):
    value, key = facts.answer_for_question("What is your CTC?")
    assert (value, key) == ("18", "compensation.current_ctc")


def test_expected_ctc_still_wins_over_bare(facts):
    value, key = facts.answer_for_question("What is your expected CTC?")
    assert (value, key) == ("28", "compensation.expected_ctc")


def test_maps_np_abbreviation_to_notice(facts):
    value, key = facts.answer_for_question("What is your NP? Mention in days")
    assert (value, key) == ("60", "compensation.notice_period_days")


def test_np_substring_does_not_false_match(facts):
    assert facts.answer_for_question("What is your favorite color?") == (None, None)


def test_maps_linkedin_url():
    from jobagent.facts import Facts
    f = Facts(data={"identity": {
        "linkedin_url": "https://www.linkedin.com/in/dharyatra-chauhan/"}})
    value, key = f.answer_for_question("What's your LinkedIn URL?")
    assert (value, key) == ("https://www.linkedin.com/in/dharyatra-chauhan/",
                            "identity.linkedin_url")


def test_maps_expected_annual_salary(facts):
    value, key = facts.answer_for_question("Expected annual salary?")
    assert (value, key) == ("28", "compensation.expected_ctc")


def test_maps_bare_annual_salary_to_current(facts):
    value, key = facts.answer_for_question("What is your annual salary?")
    assert (value, key) == ("18", "compensation.current_ctc")


def test_maps_join_days_to_notice(facts):
    value, key = facts.answer_for_question(
        "If offered the role, within how many days will you be able to join?")
    assert (value, key) == ("60", "compensation.notice_period_days")


def test_join_company_not_hijacked_by_notice(facts):
    value, key = facts.answer_for_question("Why do you want to join this company?")
    assert key == "screening_answers.why_this_company"
    assert "notice" not in key


def test_maps_hands_on_experience_to_total(facts):
    value, key = facts.answer_for_question(
        "How many years of hands-on experience do you have?")
    assert (value, key) == ("6", "experience.total_years")


def test_domain_experience_still_unmapped():
    from jobagent.facts import Facts
    f = Facts(data={"experience": {"total_years": "6"}})
    assert f.answer_for_question(
        "How many years of healthcare experience do you have?") == (None, None)


def test_missing_fact_returns_none_and_key():
    f = Facts(data={"compensation": {"current_ctc": ""}})
    value, key = f.answer_for_question("Current CTC")
    assert value is None
    assert key == "compensation.current_ctc"
    assert "current_ctc" in f.critical_missing()


def test_screening_answer_lookup(facts):
    value, key = facts.answer_for_question("What is your reason for job change?")
    assert value == "Looking for growth"


def test_onsite_and_commute_answers():
    from jobagent.facts import Facts
    f = Facts(data={"screening_answers": {
        "comfortable_with_onsite": "yes",
        "comfortable_with_commute": "yes",
    }})
    value, key = f.answer_for_question(
        "Are you comfortable working in an onsite setting?")
    assert (value, key) == ("yes", "screening_answers.comfortable_with_onsite")
    value, key = f.answer_for_question(
        "Are you comfortable commuting to this job's location?")
    assert (value, key) == ("yes", "screening_answers.comfortable_with_commute")


def test_autofill_missing_reported():
    f = Facts(data={"compensation": {}, "experience": {}})
    af = Autofill(f)
    val, key = af.resolve("What is your notice period?")
    assert val is None and key == "compensation.notice_period_days"