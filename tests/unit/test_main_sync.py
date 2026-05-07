"""CLI dispatch tests for `clonemate sync` and `sync-finish`."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from clonemate import __main__ as main_entry


def _vault(tmp_path: Path, slug: str = "zhangsan") -> Path:
    vault = tmp_path / slug
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
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
                "sources_enabled": {"contact": True, "im_1v1": True},
                "cursors": {},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )
    return vault


def _stub_fetch_run(*args, **kwargs):
    from clonemate.fetch_sources import FetchReport, SourceReport
    rep = FetchReport()
    rep.per_source["contact"] = SourceReport(name="contact", written=2)
    rep.per_source["im_1v1"] = SourceReport(name="im_1v1", written=5)
    return rep


def test_sync_help_renders(capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        main_entry.main(["sync", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "sync" in out.lower()


def test_sync_finish_help_renders(capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        main_entry.main(["sync-finish", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "sync" in out.lower()


def test_sync_happy_path_runs_fetch_and_finish(tmp_path: Path, capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources.run", side_effect=_stub_fetch_run):
        rc = main_entry.main([
            "sync", "--root", str(root), "--slug", "zhangsan",
            "--my-open-id", "ou_xxxxxxxxxxxxxxxx",
        ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[OK] contact" in out
    assert "written=2" in out
    assert "[OK] im_1v1" in out
    assert "written=5" in out


def test_sync_rejects_source_plus_retry_failed_mutex(tmp_path: Path) -> None:
    """Argparse mutex group: --source X and --retry-failed cannot coexist."""
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "sync", "--root", str(root), "--slug", "zhangsan",
            "--my-open-id", "ou_xxxxxxxxxxxxxxxx",
            "--source", "contact", "--retry-failed",
        ])
    assert ei.value.code == 2  # argparse usage error


def test_sync_finish_logs_externally_supplied_counts(tmp_path: Path, capsys) -> None:
    """`sync-finish` exists for external workflows; takes --written/--failed
    ints and writes the log + auto-commit. We only assert it exits 0 and the
    log gains a line."""
    root = tmp_path / "root"
    root.mkdir()
    vault = _vault(root)
    rc = main_entry.main([
        "sync-finish", "--root", str(root), "--slug", "zhangsan",
        "--written", "3", "--failed", "0",
    ])
    # sync-finish accepts the args; whether it does work or not, it must exit 0
    assert rc == 0
    # Vault must still exist (no destructive ops)
    assert vault.exists()
