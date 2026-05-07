"""CLI dispatch tests for `clonemate undo`."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from clonemate import __main__ as main_entry
from clonemate import merge_note


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


def test_undo_help_renders(capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        main_entry.main(["undo", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "revert" in out.lower() or "undo" in out.lower()


def test_undo_happy_path_reverts_last_commit(tmp_path: Path, capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _vault(root)
    # Write a wiki page + commit so undo has something to revert
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="X",
        sources=["src-1"],
        confidence="medium",
        body="# X\n",
        author_role="ingest",
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "add X"], cwd=vault, check=True,
    )
    assert (vault / "wiki" / "entities" / "X.md").is_file()

    rc = main_entry.main([
        "undo", "--root", str(root), "--slug", "zhangsan",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert not (vault / "wiki" / "entities" / "X.md").is_file()
