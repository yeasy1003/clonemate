"""Tests for forget_state — durable Level 2 forget state."""
from __future__ import annotations

from pathlib import Path

from clonemate import forget_state


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    state = forget_state.ForgetState(
        source="src-0013",
        started_at="2026-05-01T10:00:00+08:00",
        raw_snippets=["snippet 1", "snippet 2"],
        dirty_pages=["wiki/entities/A.md", "wiki/entities/B.md"],
    )
    forget_state.save(tmp_path, state)
    loaded = forget_state.load(tmp_path, source="src-0013")
    assert loaded == state


def test_load_returns_none_when_no_state(tmp_path: Path) -> None:
    assert forget_state.load(tmp_path, source="src-0013") is None


def test_clear_removes_state(tmp_path: Path) -> None:
    state = forget_state.ForgetState(
        source="src-0013", started_at="ts", raw_snippets=[], dirty_pages=[],
    )
    forget_state.save(tmp_path, state)
    assert forget_state.load(tmp_path, source="src-0013") is not None
    forget_state.clear(tmp_path, source="src-0013")
    assert forget_state.load(tmp_path, source="src-0013") is None


def test_save_creates_dir_with_gitignore(tmp_path: Path) -> None:
    """`.forget-state/` should never be committed."""
    state = forget_state.ForgetState(
        source="src-0013", started_at="ts", raw_snippets=[], dirty_pages=[],
    )
    forget_state.save(tmp_path, state)
    gi = tmp_path / ".forget-state" / ".gitignore"
    assert gi.is_file()
    assert "*" in gi.read_text(encoding="utf-8")
