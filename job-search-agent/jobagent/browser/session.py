"""Chrome session management.

Handles the research-backed constraint: Chrome 136+ ignores --remote-debugging-port
for the DEFAULT profile, and the default profile is locked while Chrome runs.
So we use a DEDICATED data dir and attach over CDP.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import BrowserConfig
from ..logging_setup import get_logger

log = get_logger("jobagent.browser")


class SessionDeadError(RuntimeError):
    """Raised when the logged-in session is gone (not logged in / challenged)."""


class CheckpointError(RuntimeError):
    """Raised when a CAPTCHA / security checkpoint appears. We stop, we do not bypass."""


def launch_chrome(cfg: BrowserConfig) -> subprocess.Popen | None:
    """Launch the dedicated-profile Chrome with remote debugging, if not running."""
    user_data_dir = Path(cfg.user_data_dir).resolve()
    user_data_dir.mkdir(parents=True, exist_ok=True)
    if _cdp_alive(cfg.remote_debugging_port):
        log.info("chrome already listening on %d", cfg.remote_debugging_port)
        return None
    args = [
        cfg.chrome_path,
        f"--remote-debugging-port={cfg.remote_debugging_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    log.info("launching dedicated chrome profile at %s", user_data_dir)
    return subprocess.Popen(args)


def _cdp_alive(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _pids_on_port(port: int) -> list[int]:
    """PIDs listening on a TCP port (Windows netstat). [] elsewhere/on error."""
    import platform
    if platform.system() != "Windows":
        return []
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=15).stdout or ""
    except Exception:  # noqa: BLE001
        return []
    pids: set[int] = set()
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line.upper():
            tail = line.split()
            if tail and tail[-1].isdigit():
                pids.add(int(tail[-1]))
    return sorted(pids)


def _is_chrome_pid(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout or ""
        return "chrome.exe" in out.lower()
    except Exception:  # noqa: BLE001
        return False


def relaunch_dedicated_browser(cfg: BrowserConfig) -> bool:
    """Kill a wedged Chrome holding the debugging port and relaunch our profile.

    Only touches chrome.exe processes actually holding OUR port — never the
    user's normal browser. Returns True when CDP answers afterwards.
    """
    for pid in _pids_on_port(cfg.remote_debugging_port):
        if _is_chrome_pid(pid):
            log.warning("killing wedged chrome pid %d on port %d", pid,
                        cfg.remote_debugging_port)
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=15)
            except Exception:  # noqa: BLE001
                pass
    try:
        launch_chrome(cfg)
    except Exception as e:  # noqa: BLE001
        log.error("relaunch failed: %s", e)
        return False
    for _ in range(20):
        if _cdp_alive(cfg.remote_debugging_port):
            log.info("dedicated chrome relaunched and answering")
            return True
        time.sleep(0.5)
    return False


def attach_session(cfg: BrowserConfig):
    """Attach to the dedicated Chrome, relaunching once if missing/wedged."""
    try:
        return BrowserSession(cfg).start()
    except SessionDeadError as e:
        log.warning("browser attach failed (%s); attempting one relaunch", e)
        if relaunch_dedicated_browser(cfg):
            return BrowserSession(cfg).start()
        raise


@dataclass
class BrowserSession:
    cfg: BrowserConfig
    _pw: object = None
    _browser: object = None
    _context: object = None

    def start(self):
        from playwright.sync_api import sync_playwright
        if not _cdp_alive(self.cfg.remote_debugging_port):
            launch_chrome(self.cfg)
            for _ in range(20):
                if _cdp_alive(self.cfg.remote_debugging_port):
                    break
                time.sleep(0.5)
        self._pw = sync_playwright().start()
        try:
            # Short timeout: a wedged browser can answer the HTTP endpoint yet
            # never complete the handshake (seen after OOM). Fail in 30s with
            # an actionable message instead of hanging for minutes.
            self._browser = self._pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.cfg.remote_debugging_port}",
                timeout=30000,
            )
            self._context = self._browser.contexts[0]
        except Exception as e:  # noqa: BLE001
            self.stop()
            raise SessionDeadError(
                "cannot attach to chrome: the dedicated window is missing or "
                "wedged (kill any chrome.exe holding the debugging port and "
                f"relaunch the dedicated profile): {e}") from e
        return self

    def new_page(self):
        page = self._context.new_page()
        page.set_default_navigation_timeout(self.cfg.navigation_timeout_ms)
        page.set_default_timeout(self.cfg.navigation_timeout_ms)
        return page

    def stop(self) -> None:
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._context = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def detect_checkpoint(page) -> bool:
    """Detect a login wall / captcha / checkpoint without trying to bypass it.

    Uses the URL plus VISIBLE page text only. Never page.content(): raw HTML
    includes <script> source, and LinkedIn's own bundles mention captcha and
    checkpoint handling, which used to false-positive on healthy logged-in pages.
    """
    try:
        url = (page.url or "").lower()
        if any(k in url for k in ("/checkpoint/", "/authwall", "/login", "captcha", "/challenge")):
            return True
        try:
            visible = page.inner_text("body").lower()
        except Exception:  # noqa: BLE001
            return False
        markers = (
            "are you a human", "verify you're a human", "verify you are human",
            "unusual activity", "security check", "quick security check",
            "confirm you're not a bot", "confirm you are not a bot",
            "i'm not a robot", "complete the security",
        )
        return any(m in visible for m in markers)
    except Exception:  # noqa: BLE001
        return False


def wait_for_any_selector(page, selectors: list[str], timeout_ms: int = 15000) -> str | None:
    """Return the first selector that appears, or None after the total budget."""
    if not selectors:
        return None
    per_sel = max(2000, timeout_ms // len(selectors))
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=per_sel)
            return sel
        except Exception:  # noqa: BLE001 - not present (yet); try the next
            continue
    return None


def looks_logged_out(page) -> bool:
    """Positive evidence of logged-out: a login URL or a password input."""
    try:
        url = (page.url or "").lower()
        if "/login" in url or "signin" in url or "signup" in url:
            return True
        if page.query_selector("input[type='password'], input#username, "
                               "input[name='session_password']"):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def require_logged_in(page, logged_in_selector: str, platform: str,
                      timeout_ms: int = 15000, fallbacks: list[str] | None = None) -> None:
    """Wait for a logged-in marker (SPAs need seconds to render), then verify."""
    if detect_checkpoint(page):
        raise CheckpointError(f"{platform}: checkpoint/login wall detected (url={page.url})")
    # Fast path: an actual login form on the page means logged out, no waiting.
    if looks_logged_out(page):
        raise SessionDeadError(f"{platform}: login form shown (url={page.url})")
    matched = wait_for_any_selector(page, [logged_in_selector, *(fallbacks or [])],
                                    timeout_ms=timeout_ms)
    if matched is None:
        if detect_checkpoint(page):
            raise CheckpointError(f"{platform}: checkpoint/login wall detected (url={page.url})")
        raise SessionDeadError(
            f"{platform}: not logged in in the dedicated profile (url={page.url})")