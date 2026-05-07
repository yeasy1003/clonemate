from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from clonemate import rebind_cmd


def _vault(
    tmp_path: Path,
    *,
    profile: str = "claude-code",
    app_id: str = "cli_xxxxxxxxxxxxxxxx",
) -> Path:
    vault = tmp_path / "zhangsan"
    vault.mkdir()
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": "zhangsan",
                "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx", "app_id": app_id},
                "display_name": "张三",
                "profile": profile,
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


def test_rebind_succeeds_when_app_id_matches(tmp_path: Path) -> None:
    vault = _vault(tmp_path, profile="old", app_id="cli_xxxxxxxxxxxxxxxx")
    with patch(
        "clonemate.rebind_cmd._run_whoami",
        return_value=_whoami_cp(app_id="cli_xxxxxxxxxxxxxxxx"),
    ):
        rebind_cmd.rebind(vault, new_profile="new")
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    assert cy["profile"] == "new"


def test_rebind_refuses_when_app_id_differs(tmp_path: Path) -> None:
    vault = _vault(tmp_path, app_id="cli_xxxxxxxxxxxxxxxx")
    other = "cli_yyyyyyyyyyyyyyyy"  # sanitize: allow-line plan placeholder
    with patch(
        "clonemate.rebind_cmd._run_whoami",
        return_value=_whoami_cp(app_id=other),
    ):
        with pytest.raises(rebind_cmd.RebindAppIdMismatchError):
            rebind_cmd.rebind(vault, new_profile="new")
    # profile NOT changed
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    assert cy["profile"] == "claude-code"


def test_rebind_refuses_when_whoami_fails(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with patch(
        "clonemate.rebind_cmd._run_whoami",
        return_value=_whoami_cp(returncode=1),
    ):
        with pytest.raises(rebind_cmd.RebindAppIdMismatchError):
            rebind_cmd.rebind(vault, new_profile="new")
