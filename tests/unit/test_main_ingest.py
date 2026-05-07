from __future__ import annotations

from pathlib import Path

import yaml
from clonemate import __main__ as main_entry
from clonemate import raw_writer


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
    writer = raw_writer.RawWriter(v)
    writer.write(
        raw_writer.RawCandidate(
            "contact",
            "contact/profile.md",
            "ok",
            {"author_open_id": "ou_xxxxxxxxxxxxxxxx"},
            "# 张三",
        )
    )
    return v


def test_ingest_subcommand_prints_prompt(tmp_path: Path, capsys) -> None:
    _vault(tmp_path)
    rc = main_entry.main([
        "ingest",
        "--root", str(tmp_path),
        "--slug", "zhangsan",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "target_open_id: ou_xxxxxxxxxxxxxxxx" in out
    assert "references/prompt-ingest.md" in out


def test_ingest_finish_subcommand(tmp_path: Path) -> None:
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
        "ingest-finish",
        "--root", str(tmp_path),
        "--slug", "zhangsan",
        "--raw-count", "1",
        "--wiki-count", "0",
    ])
    assert rc == 0
    assert (vault / "index.md").is_file()
    assert (vault / "log.md").is_file()
