"""Naukri chatbot modal: contenteditable answer box + question loop (no browser)."""

import time

import jobagent.autofill as af_mod
from jobagent.autofill import Autofill
from jobagent.facts import Facts


class FakeMsg:
    def __init__(self, text):
        self._text = text

    def inner_text(self):
        return self._text


class FakeBox:
    def __init__(self):
        self.filled = None
        self.pressed = []
        self.clicked = False

    def click(self):
        self.clicked = True

    def fill(self, value):
        self.filled = value

    def press(self, key):
        self.pressed.append(key)

    def evaluate(self, js, *args):
        return None


class FakeChat:
    def __init__(self, messages, box):
        self._messages = messages
        self._box = box

    def query_selector_all(self, selector):
        return self._messages

    def query_selector(self, selector):
        return self._box


class FakeChatPage:
    def __init__(self, chat):
        self._chat = chat

    def query_selector_all(self, selector):
        if "chatbot_MessageContainer" in selector:
            return [self._chat]
        return []

    def query_selector(self, selector):
        return None


def _facts_years():
    return Facts(data={
        "identity": {}, "compensation": {},
        "experience": {"total_years": "2.8"},
        "application": {}, "screening_answers": {},
    })


def _no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(af_mod.time, "sleep", lambda s: None)


def test_chat_answers_experience(monkeypatch):
    _no_sleep(monkeypatch)
    box = FakeBox()
    chat = FakeChat([
        FakeMsg("Hi Dharyatra Chauhan, thank you for showing interest. "
                "Kindly answer all the recruiter's questions to successfully "
                "apply for the job."),
        FakeMsg("How many years of experience do you have?"),
    ], box)
    af = Autofill(_facts_years())
    missing = af.fill_naukri_questions(FakeChatPage(chat), af.facts)
    assert missing == []
    assert box.filled == "2.8"
    assert "Enter" in box.pressed


def test_chat_unknown_question_reported(monkeypatch):
    _no_sleep(monkeypatch)
    box = FakeBox()
    chat = FakeChat([FakeMsg("What is your favorite color?")], box)
    empty = Facts(data={"identity": {}, "compensation": {},
                        "experience": {}, "application": {},
                        "screening_answers": {}})
    af = Autofill(empty)
    missing = af.fill_naukri_questions(FakeChatPage(chat), empty)
    assert len(missing) == 1 and "favorite color" in missing[0]
    assert box.filled is None


def test_chat_greeting_only_is_not_missing(monkeypatch):
    _no_sleep(monkeypatch)
    box = FakeBox()
    chat = FakeChat([FakeMsg("Hi Dharyatra Chauhan, thank you for showing interest.")], box)
    af = Autofill(_facts_years())
    missing = af.fill_naukri_questions(FakeChatPage(chat), af.facts)
    assert missing == []
    assert box.filled is None
