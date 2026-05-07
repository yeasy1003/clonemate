"""CLI tests for `clonemate ask` and `ask-finish`."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
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
    (v / "wiki" / "voice.md").write_text(
        "---\npage_type: voice\nsources: [src-1]\nfew_shot_count: 6\n"
        "confidence: high\n---\n\n# 总体基调\n简洁\n",
        encoding="utf-8",
    )
    return v


def test_ask_subcommand_default_mode(tmp_path: Path, capsys) -> None:
    _vault(tmp_path)
    rc = main_entry.main(
        [
            "ask",
            "--root", str(tmp_path),
            "--slug", "zhangsan",
            "--question", "ta 对 RAG 的看法?",
            "--my-open-id", "ou_xxxxxxxxxxxxxxxx",
            "--no-bg-sync",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "ta 对 RAG 的看法?" in out
    assert "voice.md" in out  # default mode reads voice.md
    assert "ask-finish" in out


def test_ask_subcommand_literal(tmp_path: Path, capsys) -> None:
    _vault(tmp_path)
    rc = main_entry.main(
        [
            "ask",
            "--root", str(tmp_path),
            "--slug", "zhangsan",
            "--question", "What is RAG?",
            "--literal",
            "--my-open-id", "ou_xxxxxxxxxxxxxxxx",
            "--no-bg-sync",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "literal" in out.lower()


def test_ask_subcommand_voice_only(tmp_path: Path, capsys) -> None:
    _vault(tmp_path)
    rc = main_entry.main(
        [
            "ask",
            "--root", str(tmp_path),
            "--slug", "zhangsan",
            "--question", "say hi",
            "--voice-only",
            "--my-open-id", "ou_xxxxxxxxxxxxxxxx",
            "--no-bg-sync",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "voice-only" in out.lower()


def test_ask_rejects_both_flags(tmp_path: Path) -> None:
    """argparse mutually-exclusive group: --literal and --voice-only can't
    both be set. Codex round 1 Finding 7: assert exit code 2 specifically,
    so the test fails on any other SystemExit (e.g. from query_cmd raising)."""
    _vault(tmp_path)
    with pytest.raises(SystemExit) as ei:
        main_entry.main(
            [
                "ask",
                "--root", str(tmp_path),
                "--slug", "zhangsan",
                "--question", "x",
                "--literal",
                "--voice-only",
            ]
        )
    assert ei.value.code == 2  # argparse usage error


def _git_init_vault(vault: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        [
            "git", "-c", "user.email=test@example.com",
            "-c", "user.name=test", "add", ".",
        ],
        cwd=vault, check=True,
    )
    subprocess.run(
        [
            "git", "-c", "user.email=test@example.com",
            "-c", "user.name=test", "commit", "-q", "-m", "init",
        ],
        cwd=vault, check=True,
    )


def test_ask_finish_subcommand_no_synthesis(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _git_init_vault(vault)
    rc = main_entry.main(
        [
            "ask-finish",
            "--root", str(tmp_path),
            "--slug", "zhangsan",
            "--question", "ta 对 RAG 的看法?",
            "--synthesis-written", "0",
        ]
    )
    assert rc == 0
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "query" in log
    assert "+0 synthesis" in log


def test_ask_finish_subcommand_with_synthesis(tmp_path: Path) -> None:
    from clonemate import merge_note

    vault = _vault(tmp_path)
    _git_init_vault(vault)
    merge_note.write(
        vault_dir=vault,
        page_type="synthesis",
        title="RAG 立场对比",
        sources=["src-1"],
        confidence="medium",
        body="# RAG 立场对比\n\n## 综述\n看法\n",
        author_role="query",
    )
    rc = main_entry.main(
        [
            "ask-finish",
            "--root", str(tmp_path),
            "--slug", "zhangsan",
            "--question", "ta 对 RAG 的看法?",
            "--synthesis-written", "1",
            "--synthesis-title", "RAG 立场对比",
        ]
    )
    assert rc == 0
    idx = (vault / "index.md").read_text(encoding="utf-8")
    assert "RAG 立场对比" in idx


def test_ask_finish_rejects_synthesis_without_title(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _git_init_vault(vault)
    with pytest.raises(SystemExit) as ei:
        main_entry.main(
            [
                "ask-finish",
                "--root", str(tmp_path),
                "--slug", "zhangsan",
                "--question", "x",
                "--synthesis-written", "1",
                # missing --synthesis-title
            ]
        )
    # argparse uses code=2 for usage errors
    assert ei.value.code == 2
