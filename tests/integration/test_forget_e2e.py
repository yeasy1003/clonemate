# tests/integration/test_forget_e2e.py
"""E2E plumbing tests for M6 forget — Level 1 / 2 / 3."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from clonemate import __main__ as main_entry
from clonemate import forget_cmd, merge_note

_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "vaults"
    / "m6-forget-fixture"
)
_FILTER_REPO_AVAILABLE = shutil.which("git-filter-repo") is not None
_skip_no_filter_repo = pytest.mark.skipif(
    not _FILTER_REPO_AVAILABLE, reason="git-filter-repo not installed",
)


def _copy(root: Path, slug: str = "zhangsan") -> Path:
    vault = root / slug
    shutil.copytree(_FIXTURE, vault)
    # Need an _clone.yaml — fixture uses placeholder slug
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    cy["slug"] = slug
    cy["display_name"] = slug
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(cy, allow_unicode=True), encoding="utf-8",
    )
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


def test_forget_level1_removes_vault_and_writes_tomb(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _copy(root, "zhangsan")
    forget_cmd.forget_level1(root, "zhangsan", yes=True)
    assert not vault.exists()
    tombs = list((root / ".forget-tombs").iterdir())
    assert tombs and "zhangsan" in tombs[0].read_text(encoding="utf-8")


def test_forget_level1_scrubs_cross_vault_syntheses(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _copy(root, "zhangsan")
    lisi = _copy(root, "lisi")
    syn = lisi / "wiki" / "syntheses" / "对比.md"
    syn.parent.mkdir(parents=True, exist_ok=True)
    syn.write_text(
        "---\npage_type: synthesis\ntitle: 对比\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n---\n\n# 对比\n"
        "参考 zhangsan/wiki/persona.md\n",
        encoding="utf-8",
    )
    forget_cmd.forget_level1(root, "zhangsan", yes=True)
    assert not (root / "zhangsan").exists()
    text = syn.read_text(encoding="utf-8")
    assert "zhangsan/wiki" not in text
    assert "(reference forgotten)" in text


def test_forget_level2_start_audits_and_emits_prompt(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _copy(root, "zhangsan")
    _git_init(vault)
    prompt = forget_cmd.forget_level2_start(vault, source="src-0013")
    assert not (vault / "raw" / "im_1v1" / "src-0013.md").exists()
    # sole-source page: pins cleared
    sole_fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "sole-source.md")
        .read_text(encoding="utf-8")
        .split("---")[1]
    )
    assert sole_fm["pinned_fields"] == []
    assert sole_fm["needs_review"] is True
    # shared-source page: confidence demoted high → medium
    shared_fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "shared-source.md")
        .read_text(encoding="utf-8")
        .split("---")[1]
    )
    assert shared_fm["confidence"] == "medium"
    assert shared_fm["needs_review"] is True
    # no-overlap page untouched
    nov_fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "no-overlap.md")
        .read_text(encoding="utf-8")
        .split("---")[1]
    )
    assert nov_fm["confidence"] == "high"
    # Prompt mentions both dirty pages
    assert "sole-source.md" in prompt
    assert "shared-source.md" in prompt


@_skip_no_filter_repo
def test_forget_level2_finish_scrubs_history(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _copy(root, "zhangsan")
    _git_init(vault)
    forget_cmd.forget_level2_start(vault, source="src-0013")
    # Simulate Claude rewrite via forget_rewrite (replaces sources, clears forget_dirty)
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="sole-source",
        sources=[], confidence="low", needs_review=True,
        body="# sole-source\n\n## (page contents removed by forget)\n",
    )
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="shared-source",
        sources=["src-0014"], confidence="medium", needs_review=True,
        body="# shared-source\n\n## 概述\n本页由 src-0014 支撑\n",
    )
    forget_cmd.forget_level2_finish(vault, source="src-0013")
    # No commit anywhere mentions src-0013
    log = subprocess.run(
        ["git", "log", "-p", "--all"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "src-0013" not in log
    # Live wiki also clean
    sole_text = (vault / "wiki" / "entities" / "sole-source.md").read_text(encoding="utf-8")
    assert "src-0013" not in sole_text


def test_forget_level3_requires_yes_i_mean_it(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _copy(root, "zhangsan")
    with pytest.raises(forget_cmd.ConfirmationRequiredError):
        forget_cmd.forget_level3_hard(root, "zhangsan")


def test_forget_level3_with_strong_confirmation_removes_vault(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _copy(root, "zhangsan")
    forget_cmd.forget_level3_hard(root, "zhangsan", yes_i_mean_it=True)
    assert not vault.exists()


def test_cli_forget_level1_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _copy(root, "zhangsan")
    rc = main_entry.main([
        "forget", "--root", str(root), "--slug", "zhangsan", "--yes",
    ])
    assert rc == 0
    assert not vault.exists()


@_skip_no_filter_repo
def test_cli_forget_level2_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _copy(root, "zhangsan")
    _git_init(vault)
    rc = main_entry.main([
        "forget", "--root", str(root), "--slug", "zhangsan",
        "--source", "src-0013",
    ])
    assert rc == 0
    # User would call Claude to rewrite via forget_rewrite. Simulate.
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="sole-source",
        sources=[], confidence="low", needs_review=True,
        body="# sole-source\n## (page contents removed by forget)\n",
    )
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="shared-source",
        sources=["src-0014"], confidence="medium", needs_review=True,
        body="# shared-source\n## 概述\n本页由 src-0014 支撑\n",
    )
    rc = main_entry.main([
        "forget-finish", "--root", str(root), "--slug", "zhangsan",
        "--source", "src-0013",
    ])
    assert rc == 0
