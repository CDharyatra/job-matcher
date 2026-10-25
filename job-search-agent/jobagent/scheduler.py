"""Windows Task Scheduler plan (free OS scheduler). Prints or installs tasks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import load_config
from .paths import HOME


def _python() -> str:
    return sys.executable


def print_plan() -> None:
    cfg = load_config()
    times = cfg.scheduler.get("run_times", ["09:15", "14:15", "20:15"])
    print("Task Scheduler plan (run in an elevated or normal PowerShell):")
    for t in times:
        print(
            f'  schtasks /Create /TN "JobAgent {t}" /SC DAILY /ST {t} '
            f'/TR "\'{_python()}\' -m jobagent.cli run"'
        )
    print("\nRun once now:  schtasks /Run /TN \"JobAgent 09:15\"")


def install_tasks() -> int:
    cfg = load_config()
    times = cfg.scheduler.get("run_times", [])
    rc = 0
    for t in times:
        cmd = [
            "schtasks", "/Create", "/F", "/TN", f"JobAgent {t}", "/SC", "DAILY",
            "/ST", t, "/TR", f'"{_python()}" -m jobagent.cli run',
        ]
        print("Running:", " ".join(cmd))
        rc |= subprocess.call(cmd)
    return rc