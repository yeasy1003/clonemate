"""E2E plumbing for M7 feed — spec §6.2 invariants."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from clonemate import __main__ as main_entry
from clonemate import feed_cmd

_FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "vaults" / "m7-sync-fixture"
)


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    shutil.copytree(_FIXTURE, vault)
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


def test_feed_text_file_writes_raw(tmp_path: Path) -> None:
    """spec §6.2: text/md file → raw/feed/* written; emit_prompt mentions
    the new raw path so Claude can run incremental ingest."""
    vault = _vault(tmp_path)
    _git_init(vault)
    f = tmp_path / "note.md"
    f.write_text("# 笔记\nta 提到 X\n", encoding="utf-8")

    with patch("clonemate.profile_check.verify_profile"):
        result = feed_cmd.feed(vault, input_arg=str(f))

    assert result.parser_name == "text"
    assert result.raws_written >= 1
    # raw file actually landed under raw/feed/
    raw_files = list((vault / "raw" / "feed").glob("*.md"))
    assert raw_files, "expected at least one raw file under raw/feed/"

    prompt = feed_cmd.emit_prompt_for_ingest(vault, result=result)
    # Prompt routes Claude to ingest the new raws — must reference paths.
    assert any(p in prompt for p in result.raw_paths)
    assert "feed-finish" in prompt


def test_feed_fact_mode_writes_wiki(tmp_path: Path) -> None:
    """spec §7.3: fact mode bypasses LLM ingest and writes a synthesis
    page directly. profile_check is NOT invoked (Codex round 1 Finding 4)."""
    vault = _vault(tmp_path)
    _git_init(vault)

    with patch("clonemate.profile_check.verify_profile") as mock_verify:
        result = feed_cmd.feed(
            vault,
            input_arg="",
            mode="fact",
            fact_text="ta 喜欢喝美式咖啡",
            confidence="medium",
            fact_title="咖啡偏好",
        )

    assert result.parser_name == "fact"
    assert mock_verify.call_count == 0, (
        "fact mode is local-only; profile_check must not be invoked"
    )
    page = vault / "wiki" / "syntheses" / "咖啡偏好.md"
    assert page.is_file()
    body = page.read_text(encoding="utf-8")
    assert "ta 喜欢喝美式咖啡" in body
    assert result.wiki_path_written == "wiki/syntheses/咖啡偏好.md"


def test_feed_unknown_input_raises_no_parser_error(tmp_path: Path) -> None:
    """spec §6.2 dispatcher: unknown suffix that is NOT extras-gated → NoParserError.
    `.xyz` doesn't match any extras hint, so the user gets a generic error."""
    vault = _vault(tmp_path)
    _git_init(vault)
    weird = tmp_path / "weird.xyz"
    weird.write_text("?", encoding="utf-8")

    with patch("clonemate.profile_check.verify_profile"):
        with pytest.raises(feed_cmd.NoParserError):
            feed_cmd.feed(vault, input_arg=str(weird))


def test_cli_feed_round_trip(tmp_path: Path, capsys) -> None:
    """Full feed → feed-finish round trip via main_entry CLI (text input)."""
    vault = _vault(tmp_path)
    _git_init(vault)
    f = tmp_path / "note.md"
    f.write_text("# 笔记\nta 在做 RAG 评估\n", encoding="utf-8")

    with patch("clonemate.profile_check.verify_profile"):
        rc = main_entry.main([
            "feed", "--root", str(tmp_path), "--slug", "zhangsan",
            "--input", str(f),
        ])
    assert rc == 0
    out = capsys.readouterr().out
    # The CLI prints the ingest prompt for Claude
    assert "feed-finish" in out
    assert "raw" in out.lower()

    # Now Claude would do ingest; we just call feed-finish with --written 0.
    rc = main_entry.main([
        "feed-finish", "--root", str(tmp_path), "--slug", "zhangsan",
        "--written", "0",
    ])
    assert rc == 0
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "feed" in log
    assert "+0 raw" in log


def test_feed_profile_mismatch_fails_fast(tmp_path: Path) -> None:
    """spec §8.7: profile gate runs BEFORE any parser dispatch.
    If verify_profile raises, feed never touches the parser registry / raw tree."""
    vault = _vault(tmp_path)
    _git_init(vault)
    f = tmp_path / "note.md"
    f.write_text("# 笔记\n", encoding="utf-8")

    raised = RuntimeError(
        "profile mismatch: vault app_id != lark-cli auth whoami app_id"
    )

    with patch("clonemate.profile_check.verify_profile", side_effect=raised), \
         patch("clonemate.feed_parsers.dispatch") as mock_dispatch:
        with pytest.raises(RuntimeError, match="profile mismatch"):
            feed_cmd.feed(vault, input_arg=str(f))

    # Critical: dispatch must NOT have been called — fail-fast gate is real.
    assert mock_dispatch.call_count == 0
    # And no raw was written.
    raw_dir = vault / "raw" / "feed"
    if raw_dir.exists():
        assert not list(raw_dir.glob("*.md"))
    # _clone.yaml profile remained intact
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    assert cy["profile"] == "claude-code"
