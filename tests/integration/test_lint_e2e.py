# tests/integration/test_lint_e2e.py
"""E2E plumbing tests for M6 lint."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml
from clonemate import __main__ as main_entry
from clonemate import lint_cmd

_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "vaults"
    / "m6-lint-fixture"
)


def _copy(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    shutil.copytree(_FIXTURE, vault)
    return vault


def _git_init(vault: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        [
            "git", "-c", "user.email=t@example.com", "-c", "user.name=t",
            "add", ".",
        ],
        cwd=vault, check=True,
    )
    subprocess.run(
        [
            "git", "-c", "user.email=t@example.com", "-c", "user.name=t",
            "commit", "-q", "-m", "init",
        ],
        cwd=vault, check=True,
    )


def test_build_report_finds_all_4_buckets(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    rpt = lint_cmd.build_report(vault)
    relpaths_orphan = [p.page_relpath for p in rpt.orphan_pages]
    assert "wiki/entities/orphan.md" in relpaths_orphan
    relpaths_missing = [p.page_relpath for p in rpt.missing_sources_pages]
    assert "wiki/entities/no-sources.md" in relpaths_missing
    refs = [(d.page_relpath, d.missing_src_id) for d in rpt.dead_refs]
    assert ("wiki/entities/dead-ref.md", "src-9999") in refs
    relpaths_stale = [s.page_relpath for s in rpt.stale_pages]
    assert any("stale.md" in p for p in relpaths_stale)


def test_emit_prompt_renders_each_section(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    prompt = lint_cmd.emit_prompt(vault)
    assert "Orphan" in prompt
    assert "Missing sources" in prompt
    assert "Dead refs" in prompt
    assert "Stale" in prompt
    assert "lint-finish" in prompt


def test_emit_prompt_clean_vault_says_clean(tmp_path: Path) -> None:
    """An empty / minimal vault produces a clean prompt."""
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "raw").mkdir()
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": "x",
                "identity": {
                    "open_id": "ou_xxxxxxxxxxxxxxxx",
                    "app_id": "cli_xxxxxxxxxxxxxxxx",
                },
                "display_name": "X",
                "profile": "claude-code",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    prompt = lint_cmd.emit_prompt(vault)
    assert "clean" in prompt.lower() or "无健康问题" in prompt


def test_lint_cli_round_trip(tmp_path: Path, capsys) -> None:
    vault = _copy(tmp_path)
    _git_init(vault)
    rc = main_entry.main([
        "lint", "--root", str(tmp_path), "--slug", "zhangsan",
    ])
    assert rc == 0
    capsys.readouterr()
    rc = main_entry.main([
        "lint-finish", "--root", str(tmp_path), "--slug", "zhangsan",
        "--findings", "4",
    ])
    assert rc == 0
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "lint" in log
    assert "4 findings" in log


def test_finish_log_says_clean_when_zero_findings(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    _git_init(vault)
    lint_cmd.finish(vault, findings=0)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "lint" in log and ("clean" in log.lower() or "0 findings" in log)
