from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from clonemate import merge_note, undo_cmd


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": "v",
                "identity": {
                    "open_id": "ou_xxxxxxxxxxxxxxxx",
                    "app_id": "cli_xxxxxxxxxxxxxxxx",
                },
                "display_name": "V",
                "profile": "claude-code",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "add",
            ".",
        ],
        cwd=vault,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        cwd=vault,
        check=True,
    )
    return vault


def test_undo_reverts_last_commit(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # Create a wiki page + commit
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
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "add",
            ".",
        ],
        cwd=vault,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "add X",
        ],
        cwd=vault,
        check=True,
    )
    assert (vault / "wiki" / "entities" / "X.md").is_file()
    undo_cmd.undo(vault)
    # Page no longer present (reverted)
    assert not (vault / "wiki" / "entities" / "X.md").is_file()
    # log.md mentions undo
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "undo" in log


def test_undo_refuses_at_root_commit(tmp_path: Path) -> None:
    """Codex round 1 Finding 5 (HIGH): refuse to revert the root commit."""
    from clonemate.undo_cmd import NothingToUndoError

    vault = _vault(tmp_path)  # _vault helper does git init + 1 commit
    # No additional commits → only 1 in HEAD
    with pytest.raises(NothingToUndoError, match="≥ 2"):
        undo_cmd.undo(vault)


def test_undo_refuses_when_not_git_repo(tmp_path: Path) -> None:
    from clonemate.undo_cmd import NothingToUndoError

    vault = tmp_path / "no-git"
    vault.mkdir()
    (vault / "_clone.yaml").write_text(
        "slug: x\nidentity:\n  open_id: ou_xxxxxxxxxxxxxxxx\n  app_id: cli_xxxxxxxxxxxxxxxx\n"
        "display_name: x\nprofile: claude-code\n",
        encoding="utf-8",
    )
    with pytest.raises(NothingToUndoError, match="not a git"):
        undo_cmd.undo(vault)
