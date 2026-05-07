from __future__ import annotations

import json
import subprocess

import pytest
from clonemate import lark_cli


def test_run_invokes_lark_cli_with_args(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"ok": True}), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # sanitize: allow-line test fixture
    out = lark_cli.run(["contact", "+get", "--user-id", "ou_xxxxxxxxxxxxxxxx"], profile="claude-code")
    assert captured["cmd"][0] == "lark-cli"
    assert "--profile" in captured["cmd"]
    assert "claude-code" in captured["cmd"]
    assert out == {"ok": True}


def test_run_raises_on_nonzero(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "", "rate limit exceeded"),
    )
    with pytest.raises(lark_cli.LarkCliError) as exc:
        lark_cli.run(["im", "+messages"], profile="claude-code")
    assert "rate limit" in str(exc.value)


def test_run_raises_on_invalid_json(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "not json", ""),
    )
    with pytest.raises(lark_cli.LarkCliError) as exc:
        lark_cli.run(["contact", "+get"], profile="claude-code")
    assert "JSON" in str(exc.value).upper()


def test_run_passes_timeout(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    lark_cli.run(["contact", "+get"], profile="claude-code", timeout=120)
    assert captured["timeout"] == 120
