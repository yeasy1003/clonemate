"""Unit tests for `query_cmd.spawn_background_sync` (M5 T2).

The function fire-and-forgets ``python -m clonemate sync ...`` after every
default-mode ``ask``. These tests verify lock-file handling, stale-lock
reclaim, min-interval gating, --retry-failed gating, log-file append mode,
and that ``subprocess.Popen`` is invoked with the right argv + ``start_new_session``.
None of the tests should ever actually launch a subprocess.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from clonemate import query_cmd


def _make_vault(tmp_path: Path, *, last_sync_run_at: str | None = None) -> Path:
    """Build a minimal vault dir with a ``_clone.yaml``.

    Pass ``last_sync_run_at`` to populate that key; pass ``None`` (default)
    to omit the key entirely (so the production code sees a 'never synced'
    state and skips the ``--retry-failed`` flag).
    """
    vault = tmp_path / "zhangsan"
    vault.mkdir()
    cy: dict[str, Any] = {
        "slug": "zhangsan",
        "identity": {
            "open_id": "ou_xxxxxxxxxxxxxxxx",
            "app_id": "cli_xxxxxxxxxxxxxxxx",
        },
        "display_name": "张三",
        "profile": "claude-code",
    }
    if last_sync_run_at is not None:
        cy["last_sync_run_at"] = last_sync_run_at
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(cy, allow_unicode=True), encoding="utf-8",
    )
    return vault


class _FakeProc:
    """Stand-in for the object ``subprocess.Popen`` returns."""

    def __init__(self, pid: int = 99999) -> None:
        self.pid = pid


def _install_fake_popen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pid: int = 99999,
) -> dict[str, Any]:
    """Replace ``subprocess.Popen`` with a recorder that returns ``_FakeProc``.

    Returns a dict capturing ``call_count``, the most-recent positional
    ``args`` and ``kwargs``, so tests can assert on them after the call.
    """
    state: dict[str, Any] = {"call_count": 0, "args": None, "kwargs": None}

    def fake_popen(*args: Any, **kwargs: Any) -> _FakeProc:
        state["call_count"] += 1
        state["args"] = args
        state["kwargs"] = kwargs
        return _FakeProc(pid=pid)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return state


def _install_failing_popen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``subprocess.Popen`` with a function that fails the test if
    it's ever called. Use when production code is supposed to short-circuit
    before spawning."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        pytest.fail(
            "subprocess.Popen must NOT be called in this scenario; "
            f"called with args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr(subprocess, "Popen", boom)


def test_spawns_when_no_lock_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)  # no _clone.yaml.last_sync_run_at means no last sync
    state = _install_fake_popen(monkeypatch, pid=99999)

    # Give it a synthetic last_sync so `--retry-failed` is appended (the no-
    # last-sync path is exercised by `test_first_sync_omits_retry_failed`).
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    cy["last_sync_run_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(cy, allow_unicode=True), encoding="utf-8",
    )

    result = query_cmd.spawn_background_sync(vault, my_open_id="ou_x")

    assert result["spawned"] is True
    assert result["pid"] == 99999

    pid_file = vault / ".bg_sync.pid"
    assert pid_file.exists()
    assert "99999" in pid_file.read_text(encoding="utf-8")

    assert state["call_count"] == 1
    cmd = state["args"][0]
    assert "-m" in cmd
    assert "clonemate" in cmd
    assert "sync" in cmd
    assert "--root" in cmd
    assert "--slug" in cmd
    assert "--my-open-id" in cmd
    assert "ou_x" in cmd
    assert "--retry-failed" in cmd

    assert state["kwargs"].get("start_new_session") is True


def test_skips_when_lock_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    # Use the test process's own PID — guaranteed to be alive.
    (vault / ".bg_sync.pid").write_text(str(os.getpid()), encoding="utf-8")

    _install_failing_popen(monkeypatch)

    result = query_cmd.spawn_background_sync(vault, my_open_id="ou_x")

    assert result["spawned"] is False
    assert "already running" in result["reason"]


def test_reclaims_stale_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    stale_pid = 999999
    (vault / ".bg_sync.pid").write_text(str(stale_pid), encoding="utf-8")

    real_kill = os.kill

    def fake_kill(pid: int, sig: int) -> None:
        if pid == stale_pid:
            raise ProcessLookupError(f"no such pid {pid}")
        real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", fake_kill)

    state = _install_fake_popen(monkeypatch, pid=12345)

    result = query_cmd.spawn_background_sync(vault, my_open_id="ou_x")

    assert result["spawned"] is True
    assert result["pid"] == 12345
    assert (vault / ".bg_sync.pid").read_text(encoding="utf-8").strip() == "12345"
    assert state["call_count"] == 1


def test_skips_when_min_interval_not_elapsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    vault = _make_vault(tmp_path, last_sync_run_at=recent)

    _install_failing_popen(monkeypatch)

    result = query_cmd.spawn_background_sync(
        vault, my_open_id="ou_x", min_interval_seconds=120,
    )

    assert result["spawned"] is False
    assert "too recent" in result["reason"]


def test_first_sync_omits_retry_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No last_sync_run_at in _clone.yaml at all.
    vault = _make_vault(tmp_path, last_sync_run_at=None)
    state = _install_fake_popen(monkeypatch, pid=42)

    result = query_cmd.spawn_background_sync(vault, my_open_id="ou_x")

    assert result["spawned"] is True
    cmd = state["args"][0]
    assert "--retry-failed" not in cmd
    assert "sync" in cmd
    assert "--my-open-id" in cmd


def test_log_file_opened_for_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    state = _install_fake_popen(monkeypatch, pid=7777)

    result = query_cmd.spawn_background_sync(vault, my_open_id="ou_x")

    assert result["spawned"] is True
    stdout_arg = state["kwargs"].get("stdout")
    # Must be a real file-like object (not a pipe/devnull constant).
    assert hasattr(stdout_arg, "write"), (
        "stdout kwarg should be a writable file handle, "
        f"got {stdout_arg!r}"
    )
    name = getattr(stdout_arg, "name", "")
    assert str(name).endswith(".bg_sync.log"), (
        f"stdout file name should end with .bg_sync.log, got {name!r}"
    )
    # Append-binary mode: production opens with `open(log_file, "ab")`.
    mode = getattr(stdout_arg, "mode", "")
    assert "a" in mode and "b" in mode, (
        f"log handle should be opened in append-binary mode, got mode={mode!r}"
    )

    # Also confirm stderr is merged into stdout.
    assert state["kwargs"].get("stderr") == subprocess.STDOUT
