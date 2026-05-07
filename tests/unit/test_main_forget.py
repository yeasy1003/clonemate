from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from clonemate import __main__ as main_entry


def _vault(root: Path, slug: str) -> Path:
    vault = root / slug
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "raw" / "im_1v1").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": slug,
                "identity": {
                    "open_id": "ou_xxxxxxxxxxxxxxxx",
                    "app_id": "cli_xxxxxxxxxxxxxxxx",
                },
                "display_name": slug,
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


def test_forget_level1_cli_requires_yes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "forget", "--root", str(root), "--slug", "zhangsan",
        ])
    assert ei.value.code == 2  # argparse usage error


def test_forget_level1_cli_with_yes_removes_vault(tmp_path: Path) -> None:
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    rc = main_entry.main([
        "forget", "--root", str(root), "--slug", "zhangsan", "--yes",
    ])
    assert rc == 0
    assert not vault.exists()


def test_forget_level3_cli_requires_strong_confirmation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "forget", "--root", str(root), "--slug", "zhangsan", "--hard",
        ])
    assert ei.value.code == 2


def test_forget_level3_cli_with_strong_confirmation_removes_vault(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    rc = main_entry.main([
        "forget", "--root", str(root), "--slug", "zhangsan",
        "--hard", "--yes-i-mean-it",
    ])
    assert rc == 0
    assert not vault.exists()


def test_forget_cli_rejects_source_plus_yes_combo(tmp_path: Path) -> None:
    """Codex round 3 Issue-K: --source (Level 2) + --yes (Level 1) is
    semantically incoherent. CLI must reject."""
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "forget", "--root", str(root), "--slug", "zhangsan",
            "--source", "src-0001", "--yes",
        ])
    assert ei.value.code == 2


def test_forget_cli_rejects_hard_plus_source_combo(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "forget", "--root", str(root), "--slug", "zhangsan",
            "--hard", "--source", "src-0001", "--yes-i-mean-it",
        ])
    assert ei.value.code == 2
