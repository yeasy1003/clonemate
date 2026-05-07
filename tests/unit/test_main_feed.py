"""CLI dispatch tests for `clonemate feed` and `feed-finish`."""
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
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return vault


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


def test_feed_help_renders_and_documents_exit_codes(capsys) -> None:
    """Codex round 4 Finding C: --help mentions exit codes 0/3/4."""
    with pytest.raises(SystemExit) as ei:
        main_entry.main(["feed", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "0" in out
    assert "3" in out
    assert "4" in out
    assert "parser" in out.lower()


def test_feed_finish_help_renders(capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        main_entry.main(["feed-finish", "--help"])
    assert ei.value.code == 0


def test_feed_happy_path_emits_ingest_prompt(tmp_path: Path, capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    note = tmp_path / "note.md"
    note.write_text("# 笔记\nbody\n", encoding="utf-8")
    with patch("clonemate.profile_check.verify_profile"):
        rc = main_entry.main([
            "feed", "--root", str(root), "--slug", "zhangsan",
            "--input", str(note),
        ])
    assert rc == 0
    out = capsys.readouterr().out
    # The emitted prompt mentions "feed" and "incremental" (or 增量)
    assert "feed" in out.lower()
    assert "incremental" in out.lower() or "增量" in out


def test_feed_fact_mode_writes_synthesis_and_prints_ok(
    tmp_path: Path, capsys
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _vault(root)
    rc = main_entry.main([
        "feed", "--root", str(root), "--slug", "zhangsan",
        "--fact", "ta 喜欢咖啡",
        "--confidence", "medium",
        "--title", "咖啡",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "咖啡" in out
    assert (vault / "wiki" / "syntheses" / "咖啡.md").is_file()


def test_feed_fact_mode_idempotent_no_op_message(tmp_path: Path, capsys) -> None:
    """Codex round 1 Finding 12: re-feeding identical fact prints
    'already exists (no changes)'."""
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    args = [
        "feed", "--root", str(root), "--slug", "zhangsan",
        "--fact", "ta 喜欢咖啡",
        "--confidence", "medium",
        "--title", "咖啡",
    ]
    main_entry.main(args)
    capsys.readouterr()  # drain
    rc = main_entry.main(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "already exists" in out or "no changes" in out


def test_feed_fact_requires_confidence_and_title(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "feed", "--root", str(root), "--slug", "zhangsan",
            "--fact", "ta 喜欢咖啡",
        ])
    assert ei.value.code == 2


def test_feed_requires_input_or_fact(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    with pytest.raises(SystemExit) as ei:
        main_entry.main([
            "feed", "--root", str(root), "--slug", "zhangsan",
        ])
    assert ei.value.code == 2


def test_feed_no_parser_returns_exit_4(tmp_path: Path, capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    weird = tmp_path / "weird.xyz"
    weird.write_text("?", encoding="utf-8")
    with patch("clonemate.profile_check.verify_profile"):
        rc = main_entry.main([
            "feed", "--root", str(root), "--slug", "zhangsan",
            "--input", str(weird),
        ])
    assert rc == 4
    err = capsys.readouterr().err
    assert "ERROR" in err or "no parser" in err.lower()


def test_feed_parser_unavailable_returns_exit_3(tmp_path: Path, capsys) -> None:
    """Codex round 3 Finding H + Finding C: extras-missing → exit 3 with
    `pip install clonemate[<extra>]` hint."""
    from clonemate import feed_cmd
    root = tmp_path / "root"
    root.mkdir()
    _vault(root)
    note = tmp_path / "doc.pdf"
    note.write_bytes(b"%PDF-fake\n")
    with patch("clonemate.profile_check.verify_profile"), \
         patch(
             "clonemate.feed_cmd.feed",
             side_effect=feed_cmd.ParserUnavailable(
                 "pdf parser needs `pip install clonemate[pdf]`"
             ),
         ):
        rc = main_entry.main([
            "feed", "--root", str(root), "--slug", "zhangsan",
            "--input", str(note),
        ])
    assert rc == 3
    err = capsys.readouterr().err
    assert "pip install" in err or "ERROR" in err


def test_feed_finish_logs_and_commits(tmp_path: Path, capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    vault = _vault(root)
    _git_init(vault)
    rc = main_entry.main([
        "feed-finish", "--root", str(root), "--slug", "zhangsan",
        "--written", "2",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "feed" in log
    assert "+2" in log
