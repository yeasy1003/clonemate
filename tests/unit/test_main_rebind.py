"""CLI dispatch tests for `clonemate rebind`."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from clonemate import __main__ as main_entry


def _vault(tmp_path: Path, slug: str = "zhangsan") -> Path:
    vault = tmp_path / slug
    vault.mkdir()
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": slug,
                "identity": {
                    "open_id": "ou_xxxxxxxxxxxxxxxx",
                    "app_id": "cli_xxxxxxxxxxxxxxxx",
                },
                "display_name": "张三",
                "profile": "claude-code",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return vault


def _whoami_cp(*, returncode: int = 0, app_id: str = "cli_xxxxxxxxxxxxxxxx"):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=json.dumps({"app_id": app_id}) if returncode == 0 else "",
        stderr="" if returncode == 0 else "auth failed",
    )


def test_rebind_help_renders(capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        main_entry.main(["rebind", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "profile" in out.lower()


def test_rebind_happy_path(tmp_path: Path, capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _vault(root)
    with patch(
        "clonemate.rebind_cmd._run_whoami",
        return_value=_whoami_cp(app_id="cli_xxxxxxxxxxxxxxxx"),
    ):
        rc = main_entry.main([
            "rebind", "--root", str(root), "--slug", "zhangsan",
            "--profile", "new-profile",
        ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    assert cy["profile"] == "new-profile"


def test_rebind_requires_profile(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "rebind", "--root", str(root), "--slug", "zhangsan",
        ])
    assert ei.value.code == 2
