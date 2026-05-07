"""parse_since — unified parser for `--since` argument forms.

Accepts: `180d` / `1y` / `2y` / `2024-01-01` / `None` (defaults to 180d).
Returns a tz-aware UTC datetime representing the cutoff.
"""
from __future__ import annotations

import datetime as _dt
import re

_DAYS_RE = re.compile(r"^(\d+)d$")
_YEARS_RE = re.compile(r"^(\d+)y$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_since(value: str | None, *, now: _dt.datetime | None = None) -> _dt.datetime:
    """Parse a since argument and return the cutoff datetime (UTC, tz-aware).

    Forms:
    - None / "180d" — N days ago (default 180)
    - "1y" / "2y"   — N years ago (365 days/year)
    - "YYYY-MM-DD"  — absolute date at midnight UTC
    """
    now = now or _dt.datetime.now(tz=_dt.timezone.utc)
    if value is None:
        return now - _dt.timedelta(days=180)
    m = _DAYS_RE.match(value)
    if m:
        return now - _dt.timedelta(days=int(m.group(1)))
    m = _YEARS_RE.match(value)
    if m:
        return now - _dt.timedelta(days=365 * int(m.group(1)))
    if _ISO_RE.match(value):
        return _dt.datetime.fromisoformat(value).replace(tzinfo=_dt.timezone.utc)
    raise ValueError(f"unrecognised --since value: {value!r}; accepted: 180d / 1y / YYYY-MM-DD")
