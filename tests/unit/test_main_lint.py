from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from clonemate import __main__ as main_entry


def _vault(tmp_path: Path) -> Path:
    v = tmp_path / "zhangsan"
    (v / "wiki" / "entities").mkdir(parents=True)
    (v / "wiki" / "concepts").mkdir(parents=True)
    (v / "wiki" / "syntheses").mkdir(parents=True)
    (v / "wiki" / "sources").mkdir(parents=True)
    (v / "raw").mkdir(parents=True)
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


def test_lint_subcommand(tmp_path: Path, capsys) -> None:
    _vault(tmp_path)
    rc = main_entry.main([
        "lint", "--root", str(tmp_path), "--slug", "zhangsan",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lint" in out.lower() or "无健康问题" in out or "clean" in out.lower()


def test_lint_finish_subcommand(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
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
        "lint-finish", "--root", str(tmp_path), "--slug", "zhangsan",
        "--findings", "0",
    ])
    assert rc == 0
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "lint" in log
