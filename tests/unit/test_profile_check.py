"""Unit tests for profile_check — sync/feed profile validation gate."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from clonemate import profile_check


def _vault(tmp_path: Path, *, profile: str = "claude-code", app_id: str = "cli_xxxxxxxxxxxxxxxx") -> Path:
    vault = tmp_path / "zhangsan"
    vault.mkdir()
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan",
        "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx", "app_id": app_id},
        "display_name": "张三",
        "profile": profile,
    }, allow_unicode=True), encoding="utf-8")
    return vault


def _mock_whoami_ok(app_id: str = "cli_xxxxxxxxxxxxxxxx"):
    """Create a CompletedProcess that mocks `lark-cli auth status` JSON output."""
    return subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({"appId": app_id, "userOpenId": "ou_xxxxxxxxxxxxxxxx"}),
        stderr="",
    )


def test_verify_profile_succeeds_when_app_id_matches(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with patch("clonemate.profile_check._run_whoami", return_value=_mock_whoami_ok()):
        # No exception raised
        profile_check.verify_profile(vault)


def test_verify_profile_raises_when_app_id_mismatches(tmp_path: Path) -> None:
    vault = _vault(tmp_path, app_id="cli_xxxxxxxxxxxxxxxx")
    other_app = "cli_yyyyyyyyyyyyyyyy"  # sanitize: allow-line plan placeholder
    with patch(
        "clonemate.profile_check._run_whoami",
        return_value=_mock_whoami_ok(app_id=other_app),
    ):
        with pytest.raises(profile_check.ProfileMismatchError, match="app_id"):
            profile_check.verify_profile(vault)


def test_verify_profile_raises_when_whoami_fails(tmp_path: Path) -> None:
    """lark-cli not authenticated → returncode != 0 → raise with login hint."""
    vault = _vault(tmp_path)
    failed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="not authenticated",
    )
    with patch("clonemate.profile_check._run_whoami", return_value=failed):
        with pytest.raises(profile_check.ProfileMismatchError, match="lark-cli auth login"):
            profile_check.verify_profile(vault)


def test_verify_profile_raises_when_whoami_json_invalid(tmp_path: Path) -> None:
    """Defensive: malformed JSON from lark-cli → clear error."""
    vault = _vault(tmp_path)
    bad = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not json", stderr="",
    )
    with patch("clonemate.profile_check._run_whoami", return_value=bad):
        with pytest.raises(profile_check.ProfileMismatchError, match="JSON"):
            profile_check.verify_profile(vault)
