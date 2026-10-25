"""Human-like pacing helpers. No overnight blasting, no parallel pages."""

from __future__ import annotations

import random
import time
from datetime import datetime

from ..config import ApplyConfig


def sleep_between(min_seconds: int, spread: float = 0.6) -> None:
    delay = min_seconds + random.uniform(0, max(1.0, min_seconds * spread))
    time.sleep(delay)


def _hm(value: str | None, default: tuple[int, int]) -> tuple[int, int]:
    """Parse 'H:MM'/'HH:MM' into (hour, minute); string comparison of times is
    wrong ('7:00' > '08:00' lexically), so compare numerically."""
    try:
        h, m = str(value).split(":")
        h_i, m_i = int(h), int(m)
        if 0 <= h_i <= 23 and 0 <= m_i <= 59:
            return h_i, m_i
    except (ValueError, AttributeError):
        pass
    return default


def in_quiet_hours(cfg: ApplyConfig, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    start = _hm(cfg.quiet_hours.get("start", "22:30"), (22, 30))
    end = _hm(cfg.quiet_hours.get("end", "08:00"), (8, 0))
    cur = (now.hour, now.minute)
    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end  # crosses midnight


def human_scroll(page, steps: int = 3) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, random.randint(300, 700))
        time.sleep(random.uniform(0.4, 1.1))