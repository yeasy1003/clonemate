"""Tests for parse_since.py."""
from __future__ import annotations

import datetime as _dt

import pytest
from clonemate import parse_since

# Anchor "now" to a fixed moment for deterministic tests.
_NOW = _dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=_dt.timezone.utc)


def test_days_form() -> None:
    assert parse_since.parse_since("180d", now=_NOW) == _NOW - _dt.timedelta(days=180)


def test_years_form_1y() -> None:
    assert parse_since.parse_since("1y", now=_NOW) == _NOW - _dt.timedelta(days=365)


def test_years_form_2y() -> None:
    assert parse_since.parse_since("2y", now=_NOW) == _NOW - _dt.timedelta(days=730)


def test_iso_date_form() -> None:
    out = parse_since.parse_since("2024-01-01", now=_NOW)
    assert out.year == 2024 and out.month == 1 and out.day == 1
    assert out.tzinfo is not None  # must be tz-aware


def test_invalid_form_raises() -> None:
    with pytest.raises(ValueError) as exc:
        parse_since.parse_since("yesterday", now=_NOW)
    assert "yesterday" in str(exc.value)


def test_default_when_none() -> None:
    """parse_since(None) returns 180 days ago — the spec default."""
    assert parse_since.parse_since(None, now=_NOW) == _NOW - _dt.timedelta(days=180)
