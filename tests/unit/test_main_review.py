from __future__ import annotations

from pathlib import Path

import yaml
from clonemate import __main__ as main_entry


def _vault(tmp_path: Path) -> Path:
    v = tmp_path / "zhangsan"
    (v / "raw").mkdir(parents=True)
    (v / "wiki" / "entities").mkdir(parents=True)
    (v / "wiki" / "concepts").mkdir(parents=True)
    (v / "wiki" / "syntheses").mkdir(parents=True)
    (v / "wiki" / "sources").mkdir(parents=True)
    (v / "_clone.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": "zhangsan",
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
    return v


def test_review_subcommand_emits_prompt(tmp_path: Path, capsys) -> None:
    _vault(tmp_path)
    rc = main_entry.main(["review", "--root", str(tmp_path), "--slug", "zhangsan"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Phase B/C" in out or "无需复核" in out


def test_review_finish_subcommand(tmp_path: Path) -> None:
    import subprocess

    vault = _vault(tmp_path)
    # Initialize git so finish() can auto-commit (Codex round 3 Finding 9).
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )
    rc = main_entry.main([
        "review-finish",
        "--root", str(tmp_path),
        "--slug", "zhangsan",
        "--resolved", "2",
        "--skipped", "1",
    ])
    assert rc == 0
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "review" in log and "+2 resolved / +1 skipped" in log
