"""HTTP via the OS curl binary (Windows ships curl.exe).

Why this exists: some endpoints (notably opencode.ai, behind Cloudflare bot
management) reject Python-urllib's TLS fingerprint with HTTP 403/1010 while the
same request through curl succeeds. urllib stays the default everywhere; curl
is used only for providers that need it. No new dependencies, no cost.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class CurlHTTPError(Exception):
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def curl_available() -> bool:
    return shutil.which("curl") is not None


def _run(args: list[str], timeout: int) -> tuple[int, str]:
    proc = subprocess.run(["curl", "-s", "--max-time", str(timeout)] + args,
                          capture_output=True, timeout=timeout + 10)
    out = (proc.stdout or b"").decode("utf-8", errors="ignore")
    # curl -w appends "<newline><status>" AFTER the body.
    body, _, status_str = out.rpartition("\n")
    try:
        return int(status_str.strip()), body
    except ValueError:
        raise CurlHTTPError(-1, out[:200])


def curl_get_json(url: str, headers: dict[str, str], timeout: int) -> tuple[int, object]:
    args = ["-w", "\n%{http_code}"]
    for k, v in headers.items():
        args += ["-H", f"{k}: {v}"]
    args.append(url)
    status, body = _run(args, timeout)
    try:
        return status, json.loads(body) if body.strip() else None
    except json.JSONDecodeError:
        return status, body


def curl_post_json(url: str, body: dict, headers: dict[str, str],
                   timeout: int) -> tuple[int, object]:
    # Body goes through a temp file (never on the command line). The mkstemp
    # fd must be closed first: on Windows an open handle locks the file.
    fd, name = tempfile.mkstemp(suffix=".json")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(body))
        args = ["-X", "POST", "-w", "\n%{http_code}"]
        for k, v in headers.items():
            args += ["-H", f"{k}: {v}"]
        args += ["--data-binary", "@" + str(tmp), url]
        status, text = _run(args, timeout)
    finally:
        tmp.unlink(missing_ok=True)
    try:
        return status, json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        return status, text