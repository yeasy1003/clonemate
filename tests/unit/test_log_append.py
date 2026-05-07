"""Tests for log_append.py."""
from __future__ import annotations

from pathlib import Path

from clonemate import log_append


def test_appends_to_existing_log(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    log.write_text("# Log\n\n## [2026-04-29 10:00] init | zhangsan | new vault\n", encoding="utf-8")
    log_append.append(log, op="ingest", subject="initial-clone", metric="+10 raw / +5 wiki")
    text = log.read_text(encoding="utf-8")
    assert "init | zhangsan | new vault" in text
    assert "ingest | initial-clone | +10 raw / +5 wiki" in text
    # last line is the new entry; original line preserved
    assert text.count("## [") == 2


def test_creates_log_when_missing(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    log_append.append(log, op="lint", subject="weekly", metric="0 issues")
    text = log.read_text(encoding="utf-8")
    assert text.startswith("# Log")
    assert "lint | weekly | 0 issues" in text


def test_timestamp_format_iso_minute(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    log_append.append(log, op="ingest", subject="x", metric="y")
    line = log.read_text(encoding="utf-8").splitlines()[-1]
    # `## [YYYY-MM-DD HH:MM] op | subject | metric`
    assert line.startswith("## [")
    bracket_close = line.index("]")
    ts = line[len("## ["):bracket_close]
    # YYYY-MM-DD HH:MM = 16 chars
    assert len(ts) == 16
    assert ts[4] == "-" and ts[7] == "-" and ts[10] == " " and ts[13] == ":"


def test_grep_friendly_format(tmp_path: Path) -> None:
    """`grep '^## \\[' log.md | tail -5` should isolate the last 5 entries."""
    log = tmp_path / "log.md"
    for i in range(7):
        log_append.append(log, op="ingest", subject=f"batch-{i}", metric=f"+{i}")
    grep_lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("## [")]
    assert len(grep_lines) == 7
    # Last 5 should be batches 2..6
    last5 = grep_lines[-5:]
    for i, line in enumerate(last5, start=2):
        assert f"batch-{i}" in line
