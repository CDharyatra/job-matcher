"""fill_dialog + dialog helpers against a fake DOM (no browser)."""

from jobagent.autofill import Autofill
from jobagent.facts import Facts


class FakeEl:
    def __init__(self, tag="div", attrs=None, text="", children=None,
                 options=None, container="", visible=True, sibling=""):
        self._tag = tag
        self._attrs = dict(attrs or {})
        self._text = text
        self._children = list(children or [])
        self._options = options or []
        self._container = container
        self._visible = visible
        self._sibling = sibling
        self.filled = None
        self.selected = None
        self.checked = False
        self.uploaded = None
        self.clicked = False

    # playwright-ish surface used by autofill
    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self):
        return self._text

    def is_visible(self):
        return getattr(self, "_visible", True)

    def is_enabled(self):
        return True

    def is_checked(self):
        return self.checked

    def evaluate(self, js):
        if "let p = e.parentElement" in js:
            return self._sibling
        if "closest('fieldset')" in js:
            return self._container
        if "tagName.toLowerCase()" in js:
            return self._tag
        if "Array.from(e.options)" in js:
            return [f"{t}|||{v}" for t, v in self._options]
        return ""

    def fill(self, value):
        self.filled = value

    def select_option(self, label=None, value=None):
        opts = [t for t, _ in self._options]
        vals = [v for _, v in self._options]
        if label is not None and label not in opts:
            raise ValueError("no such label")
        if value is not None and value not in vals:
            raise ValueError("no such value")
        self.selected = label if label is not None else value

    def check(self, *args, **kwargs):
        self.checked = True
        self.check_kwargs = kwargs

    def set_input_files(self, path):
        self.uploaded = path

    def click(self):
        self.clicked = True

    def query_selector(self, selector):
        for child in self._children:
            if _matches(child, selector):
                return child
        return None

    def query_selector_all(self, selector):
        return [c for c in self._children if _matches(c, selector)]


def _matches(el, selector):
    for part in selector.split(","):
        part = part.strip()
        if part.startswith("input[type='"):
            want = part.split("'")[1]
            if el._tag == "input" and (el._attrs.get("type") or "") == want:
                return True
        elif part.startswith("input["):
            if el._tag == "input":
                return True
        elif part in ("input", "textarea", "select", "button"):
            if el._tag == part:
                return True
    return False


class FakeDialog(FakeEl):
    def __init__(self, children):
        super().__init__(tag="dialog", attrs={}, children=children)


class FakePage:
    def __init__(self, dialog=None):
        self._dialog = dialog

    def query_selector(self, selector):
        if self._dialog is None:
            return None
        if "dialog" in selector:
            return self._dialog
        return None


def facts():
    return Facts(data={
        "identity": {"full_name": "Test User", "email": "test@example.com",
                     "phone": "9876543210", "phone_country_code": "+91",
                     "current_city": "Bengaluru",
                     "willing_to_relocate": "yes"},
        "compensation": {"current_ctc": "18", "expected_ctc": "28",
                         "notice_period_days": "60"},
        "experience": {"total_years": "3"},
        "application": {"resume_files": []},
        "screening_answers": {},
    })


def test_find_dialog_variants():
    from jobagent.browser import linkedin as li

    class P(FakePage):
        def query_selector(self, selector):
            return FakeDialog([]) if "dialog" in selector else None

    assert li.find_easy_apply_dialog(P()) is not None
    assert li.find_easy_apply_dialog(FakePage()) is None


def test_contact_step_fills_email_country_phone():
    af = Autofill(facts())
    email = FakeEl("select", {"aria-label": "Email address"},
                   options=[("other@x.com", "other@x.com"),
                            ("test@example.com", "test@example.com")])
    country = FakeEl("select", {"aria-label": "Phone country code"},
                     options=[("United States (+1)", "us"),
                              ("India (+91)", "in")])
    phone = FakeEl("input", {"type": "tel", "aria-label": "Phone number"})
    page = FakePage(FakeDialog([email, country, phone]))
    missing, notes = af.fill_dialog(page, facts(), resume_path=None)
    assert missing == []
    assert email.selected == "test@example.com"
    assert country.selected == "India (+91)"
    assert phone.filled == "9876543210"


def test_country_code_exact_match_not_substring():
    # Regression: "+91" must select India, never Bolivia (+591).
    af = Autofill(facts())
    country = FakeEl("select", {"aria-label": "Phone country code"},
                     options=[("Bolivia (+591)", "bo"),
                              ("India (+91)", "in")])
    page = FakePage(FakeDialog([country]))
    missing, _ = af.fill_dialog(page, facts(), resume_path=None)
    assert missing == []
    assert country.selected == "India (+91)"


def test_email_keeps_default_when_facts_address_absent():
    af = Autofill(facts())
    email = FakeEl("select", {"aria-label": "Email address"},
                   options=[("uni@college.edu", "uni@college.edu")])
    page = FakePage(FakeDialog([email]))
    missing, notes = af.fill_dialog(page, facts(), resume_path=None)
    assert missing == []
    assert email.selected is None
    assert any("account-default" in n for n in notes)


def test_radio_yes_no_from_facts():
    af = Autofill(facts())
    yes = FakeEl("input", {"type": "radio", "name": "q1",
                           "aria-label": "Yes, willing to relocate"})
    no = FakeEl("input", {"type": "radio", "name": "q1",
                          "aria-label": "No"})
    page = FakePage(FakeDialog([yes, no]))
    missing, _ = af.fill_dialog(page, facts(), resume_path=None)
    # 'relocat' maps to willing_to_relocate=yes; either outcome must not invent
    assert missing == [] or all("relocate" in m or "question" in m for m in missing)
    assert not no.checked  # never checks "No" when facts say yes


def test_unknown_required_question_reported():
    af = Autofill(Facts(data={"identity": {}, "compensation": {},
                              "experience": {}, "application": {},
                              "screening_answers": {}}))
    inp = FakeEl("input", {"type": "text",
                           "aria-label": "What is your favorite color? *"})
    page = FakePage(FakeDialog([inp]))
    missing, _ = af.fill_dialog(page, af.facts, resume_path=None)
    assert any("favorite color" in m for m in missing)
    assert inp.filled is None


def test_resume_upload_and_missing_file(tmp_path):
    af = Autofill(facts())
    finput = FakeEl("input", {"type": "file"})
    page = FakePage(FakeDialog([finput]))
    missing, _ = af.fill_dialog(page, facts(), resume_path=None)
    assert missing == ["application.resume_files"]
    good = tmp_path / "cv.pdf"
    good.write_bytes(b"%PDF-1.4 fake")
    missing, notes = af.fill_dialog(page, facts(), resume_path=str(good))
    assert missing == []
    assert finput.uploaded == str(good)
    assert any("resume" in n for n in notes)


def test_radio_uses_container_question_not_option_text():
    # Live shape: bare Yes/No options; the question lives in the container.
    # Option text alone ("Yes / No") must never drive the answer.
    from jobagent.facts import Facts
    f = Facts(data={"screening_answers": {"comfortable_with_onsite": "yes"}})
    af = Autofill(f)
    container = "Are you comfortable working in an onsite setting?* Yes No"
    yes = FakeEl("input", {"type": "radio", "name": "q1", "value": "Yes"},
                 container=container)
    no = FakeEl("input", {"type": "radio", "name": "q1", "value": "No"},
                container=container)
    # option texts are bare: _radio_text finds nothing
    page = FakePage(FakeDialog([yes, no]))
    missing, _ = af.fill_dialog(page, f, resume_path=None)
    assert missing == []
    assert yes.checked and not no.checked


def test_radio_shared_aria_question_with_option_values():
    # Live LinkedIn shape: identical long aria (the question) on every option,
    # Yes/No distinguished only by value/label. Must resolve via the question
    # and click the matching option.
    from jobagent.facts import Facts
    f = Facts(data={"screening_answers": {"comfortable_with_commute": "yes"}})
    af = Autofill(f)
    q = "Are you comfortable commuting to this job's location?"
    yes = FakeEl("input", {"type": "radio", "name": "q2", "value": "Yes",
                           "aria-label": q})
    no = FakeEl("input", {"type": "radio", "name": "q2", "value": "No",
                          "aria-label": q})
    page = FakePage(FakeDialog([yes, no]))
    missing, _ = af.fill_dialog(page, f, resume_path=None)
    assert missing == []
    assert yes.checked and not no.checked


def test_text_input_block_asterisk_reported():
    # Domain-specific question (healthcare years) with no stored answer and a
    # "*" in the block: must fail loudly, never invent, never skip.
    af = Autofill(Facts(data={"identity": {}, "compensation": {},
                              "experience": {"total_years": "2.8"},
                              "application": {}, "screening_answers": {}}))
    inp = FakeEl("input", {"type": "text",
                           "aria-label": "How many years of Health Care "
                                         "Provider experience do you have?"},
                 container="How many years of Health Care Provider experience "
                           "do you have?*")
    page = FakePage(FakeDialog([inp]))
    missing, _ = af.fill_dialog(page, af.facts, resume_path=None)
    assert len(missing) == 1 and "health care provider" in missing[0]
    assert inp.filled is None


def test_radio_required_star_reported_not_skipped():
    af = Autofill(Facts(data={"identity": {}, "compensation": {},
                              "experience": {}, "application": {},
                              "screening_answers": {}}))
    yes = FakeEl("input", {"type": "radio", "name": "q9",
                           "aria-label": "Yes, comfortable onsite"})
    no = FakeEl("input", {"type": "radio", "name": "q9",
                          "aria-label": "No"})
    # simulate the "*" LinkedIn appends to required questions
    yes._attrs["aria-label"] = "Yes, comfortable onsite *"
    page = FakePage(FakeDialog([yes, no]))
    missing, _ = af.fill_dialog(page, af.facts, resume_path=None)
    assert len(missing) == 1 and "onsite" in missing[0]
    assert not yes.checked and not no.checked


def test_hidden_radio_uses_sibling_text_and_force_checks():
    # Live shape: invisible native inputs, question in shared aria, option
    # text only beside each input. Must resolve, then force-check Yes.
    from jobagent.facts import Facts
    f = Facts(data={"screening_answers": {"comfortable_with_onsite": "yes"}})
    af = Autofill(f)
    q = "Are you comfortable working in an onsite setting?"
    yes = FakeEl("input", {"type": "radio", "name": "q1", "aria-label": q},
                 visible=False, sibling="Yes")
    no = FakeEl("input", {"type": "radio", "name": "q1", "aria-label": q},
                visible=False, sibling="No")
    page = FakePage(FakeDialog([yes, no]))
    missing, _ = af.fill_dialog(page, f, resume_path=None)
    assert missing == []
    assert yes.checked and not no.checked
    assert yes.check_kwargs.get("force") is True


def test_no_blind_check_without_question():
    from jobagent.facts import Facts
    f = Facts(data={"screening_answers": {"comfortable_with_onsite": "yes"}})
    af = Autofill(f)
    blob = FakeEl("input", {"type": "radio", "name": "q1"},
                  sibling="Yes No")
    real = FakeEl("input", {"type": "radio", "name": "q1"},
                  sibling="Yes")
    page = FakePage(FakeDialog([blob, real]))
    # question unresolvable here (no keywords); must not check blindly
    missing, _ = af.fill_dialog(
        page, Facts(data={"identity": {}, "compensation": {},
                          "experience": {}, "application": {},
                          "screening_answers": {}}), resume_path=None)
    assert not real.checked and not blob.checked


def test_dialog_button_exact_match():
    from jobagent.browser import linkedin as li
    yes_btn = FakeEl("button", {}, text="Next")
    other = FakeEl("button", {}, text="Next job alert")
    dialog = FakeDialog([yes_btn, other])
    assert li._dialog_button(dialog, "Next") is yes_btn
    assert li._dialog_button(dialog, "Submit application") is None


def test_dialog_success_markers():
    from jobagent.browser import linkedin as li

    class ToastPage:
        def query_selector(self, selector):
            return None

        def query_selector_all(self, selector):
            if "toast" in selector:
                return [FakeEl("div", {}, text="Your application was sent!")]
            return []

    assert li._dialog_success(ToastPage()) is True

    class EmptyPage(ToastPage):
        def query_selector_all(self, selector):
            return []

    assert li._dialog_success(EmptyPage()) is False