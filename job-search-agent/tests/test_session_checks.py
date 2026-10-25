import pytest

from jobagent.browser.session import (CheckpointError, SessionDeadError, detect_checkpoint,
                                      looks_logged_out, require_logged_in,
                                      wait_for_any_selector)


class FakePage:
    def __init__(self, url="https://www.linkedin.com/feed/", visible="",
                 selector_hits=True):
        self.url = url
        self._visible = visible
        self._hits = selector_hits

    def inner_text(self, _selector):
        return self._visible

    def query_selector(self, _selector):
        return None  # no login form by default

    def wait_for_selector(self, selector, timeout=None):
        hits = self._hits if isinstance(self._hits, set) else None
        if hits is not None:
            if selector in hits:
                return True
            raise TimeoutError("waiting for selector")
        if not self._hits:
            raise TimeoutError("waiting for selector")
        return True


def test_script_mentions_do_not_trigger_checkpoint():
    # Regression: page.content() includes <script> source where LinkedIn's own
    # bundles mention captcha/checkpoint code. Detection must use visible text.
    page = FakePage(visible="Home Feed. Start a post. Senior Backend Engineer hiring.")
    assert not detect_checkpoint(page)


def test_visible_checkpoint_text_triggers():
    page = FakePage(url="https://www.linkedin.com/feed/",
                    visible="Let's do a quick security check before you continue.")
    assert detect_checkpoint(page)


def test_checkpoint_url_triggers():
    page = FakePage(url="https://www.linkedin.com/checkpoint/challenge/")
    assert detect_checkpoint(page)


def test_login_url_triggers():
    page = FakePage(url="https://www.linkedin.com/login?trk=feed")
    assert detect_checkpoint(page)


def test_require_logged_in_waits_and_passes():
    page = FakePage()
    require_logged_in(page, "img.global-nav__me-photo", "linkedin")  # no raise


def test_require_logged_in_raises_session_dead_with_url():
    page = FakePage(selector_hits=False)
    with pytest.raises(SessionDeadError, match="linkedin.*linkedin.com/feed"):
        require_logged_in(page, "img.global-nav__me-photo", "linkedin")


def test_require_logged_in_prefers_checkpoint():
    page = FakePage(visible="Verify you're a human to continue.", selector_hits=False)
    with pytest.raises(CheckpointError):
        require_logged_in(page, "img.global-nav__me-photo", "linkedin")


def test_wait_for_any_selector_tries_fallbacks():
    page = FakePage(selector_hits={"nav.global-nav"})
    assert wait_for_any_selector(page, ["img.missing", "nav.global-nav"]) == "nav.global-nav"


def test_wait_for_any_selector_returns_none():
    page = FakePage(selector_hits=set())
    assert wait_for_any_selector(page, ["a", "b"], timeout_ms=4000) is None


def test_require_logged_in_uses_fallbacks():
    page = FakePage(selector_hits={"nav.global-nav"})
    require_logged_in(page, "img.global-nav__me-photo", "linkedin",
                      fallbacks=["nav.global-nav"])  # no raise


def test_login_form_is_instant_session_dead():
    class LoginPage(FakePage):
        def query_selector(self, _selector):
            return object()  # a password/username input is present

    with pytest.raises(SessionDeadError, match="login form shown"):
        require_logged_in(LoginPage(), "img.global-nav__me-photo", "linkedin")


def test_looks_logged_out_password_input():
    class LoginPage(FakePage):
        def query_selector(self, _selector):
            return object()

    assert looks_logged_out(LoginPage())
    assert not looks_logged_out(FakePage())


def test_looks_logged_out_login_url():
    assert looks_logged_out(FakePage(url="https://www.naukri.com/account/login"))
    assert not looks_logged_out(FakePage(url="https://www.naukri.com/mnjuser/homepage"))