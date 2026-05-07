"""Shared pytest fixtures."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Project repo root (the directory containing pyproject.toml)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def empty_vault_dir(tmp_path: Path) -> Path:
    """Empty directory destined to become a vault. Returned path is created and empty."""
    d = tmp_path / "vault-zhangsan"
    d.mkdir()
    return d


@pytest.fixture
def fake_lark_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Stub lark-cli; tests can configure return values via .returns dict.

    Convention: production modules MUST use `import subprocess; subprocess.run(...)`,
    NOT `from subprocess import run; run(...)`. The latter binds `run` in the caller's
    namespace at import time and bypasses this monkeypatch.
    """
    state: dict[str, Any] = {"returns": {}, "calls": []}

    def fake_run(cmd, *args, **kwargs):
        state["calls"].append(cmd)
        for pattern, retval in state["returns"].items():
            if isinstance(cmd, list) and pattern in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 0, retval, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return state
