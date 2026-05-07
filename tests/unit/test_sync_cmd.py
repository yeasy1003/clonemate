"""Unit tests for sync_cmd — incremental fetch with profile gating."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from clonemate import sync_cmd


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan",
        "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx", "app_id": "cli_xxxxxxxxxxxxxxxx"},
        "display_name": "张三",
        "profile": "claude-code",
        "sources_enabled": {"contact": True, "im_1v1": True, "minutes": False},
        "cursors": {},
    }, allow_unicode=True), encoding="utf-8")
    return vault


def _stub_fetch_sources_run(*args, **kwargs):
    from clonemate.fetch_sources import FetchReport, SourceReport
    rep = FetchReport()
    rep.per_source["contact"] = SourceReport(name="contact", written=1)
    rep.per_source["im_1v1"] = SourceReport(name="im_1v1", written=3)
    return rep


def test_sync_calls_profile_check_before_fetch(tmp_path: Path) -> None:
    """spec §8.7: profile validation runs BEFORE any fetch."""
    vault = _vault(tmp_path)
    profile_calls: list[Path] = []

    def fake_verify(vd: Path) -> None:
        profile_calls.append(vd)

    with patch("clonemate.profile_check.verify_profile", side_effect=fake_verify), \
         patch("clonemate.fetch_sources.run", side_effect=_stub_fetch_sources_run):
        sync_cmd.sync(vault, my_open_id="ou_xxxxxxxxxxxxxxxx")
    assert profile_calls == [vault]


def test_sync_propagates_profile_mismatch(tmp_path: Path) -> None:
    """If verify_profile raises, sync fails fast (no fetch)."""
    from clonemate.profile_check import ProfileMismatchError
    vault = _vault(tmp_path)
    with patch(
        "clonemate.profile_check.verify_profile",
        side_effect=ProfileMismatchError("nope"),
    ), patch("clonemate.fetch_sources.run") as mock_run:
        with pytest.raises(ProfileMismatchError):
            sync_cmd.sync(vault, my_open_id="ou_xxxxxxxxxxxxxxxx")
    mock_run.assert_not_called()


def test_sync_with_source_filter_only_runs_named_source(tmp_path: Path) -> None:
    """`--source <name>` filters sources_enabled to just that source.
    Other sources_enabled are temporarily disabled for the run."""
    vault = _vault(tmp_path)
    captured_yaml: list[dict] = []

    def fake_run(*, vault_dir: Path, **kwargs):
        # Read _clone.yaml at fetch time (after sync_cmd's filter is applied)
        captured_yaml.append(yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8")))
        return _stub_fetch_sources_run()

    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources.run", side_effect=fake_run):
        sync_cmd.sync(
            vault, my_open_id="ou_xxxxxxxxxxxxxxxx",
            source_filter="im_1v1",
        )
    assert captured_yaml
    enabled = captured_yaml[0]["sources_enabled"]
    assert enabled.get("im_1v1") is True
    assert enabled.get("contact") is False
    assert enabled.get("minutes") is False


def test_sync_with_source_filter_restores_yaml_after_run(tmp_path: Path) -> None:
    """After sync returns, _clone.yaml.sources_enabled must be restored."""
    vault = _vault(tmp_path)
    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources.run", side_effect=_stub_fetch_sources_run):
        sync_cmd.sync(
            vault, my_open_id="ou_xxxxxxxxxxxxxxxx",
            source_filter="contact",
        )
    enabled = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))["sources_enabled"]
    assert enabled["contact"] is True
    assert enabled["im_1v1"] is True   # restored
    assert enabled["minutes"] is False  # restored


def test_sync_with_retry_failed_only_runs_failed_sources(tmp_path: Path) -> None:
    """`--retry-failed` filters sources_enabled to only those whose last
    cursor has status: 'failed'."""
    vault = _vault(tmp_path)
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    cy["cursors"] = {
        "contact": {"status": "ok"},
        "im_1v1": {"status": "failed", "last_error": "rate limited"},
    }
    (vault / "_clone.yaml").write_text(yaml.safe_dump(cy, allow_unicode=True), encoding="utf-8")

    captured: list[dict] = []
    def fake_run(*, vault_dir: Path, **kwargs):
        captured.append(yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8")))
        return _stub_fetch_sources_run()

    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources.run", side_effect=fake_run):
        sync_cmd.sync(
            vault, my_open_id="ou_xxxxxxxxxxxxxxxx", retry_failed=True,
        )
    enabled = captured[0]["sources_enabled"]
    assert enabled["im_1v1"] is True
    assert enabled["contact"] is False  # ok status → skipped


def _git_init(vault: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )


def test_finish_logs_per_source_summary(tmp_path: Path) -> None:
    from clonemate.fetch_sources import FetchReport, SourceReport
    vault = _vault(tmp_path)
    _git_init(vault)
    rep = FetchReport()
    rep.per_source["contact"] = SourceReport(name="contact", written=1)
    rep.per_source["im_1v1"] = SourceReport(
        name="im_1v1", failed=True, error="rate limited",
    )
    sync_cmd.finish(vault, report=rep)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "sync" in log
    assert "+1" in log
    assert "FAIL" in log or "failed" in log


def test_finish_auto_commits_state(tmp_path: Path) -> None:
    from clonemate.fetch_sources import FetchReport
    vault = _vault(tmp_path)
    _git_init(vault)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True, check=True,
    ).stdout.strip()
    sync_cmd.finish(vault, report=FetchReport())
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault, capture_output=True, text=True, check=True,
    ).stdout.strip()
    # log.md changed → HEAD advances
    assert head_after != head_before
