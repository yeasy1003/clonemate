"""Tests for feed_cmd."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from clonemate import feed_cmd


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(
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
    return vault


def test_feed_writes_raw_for_md_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    f = tmp_path / "note.md"
    f.write_text("# 笔记\nbody\n", encoding="utf-8")
    with patch("clonemate.profile_check.verify_profile"):
        result = feed_cmd.feed(vault, input_arg=str(f))
    assert result.parser_name == "text"
    assert result.raws_written >= 1


def test_feed_fact_mode_writes_wiki_directly(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with patch("clonemate.profile_check.verify_profile"):
        result = feed_cmd.feed(
            vault,
            input_arg="",
            mode="fact",
            fact_text="ta 喜欢咖啡",
            confidence="medium",
            fact_title="咖啡",
        )
    assert result.parser_name == "fact"
    assert (vault / "wiki" / "syntheses" / "咖啡.md").is_file()


def test_feed_unknown_input_raises(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    f = tmp_path / "weird.xyz"
    f.write_text("?", encoding="utf-8")
    with patch("clonemate.profile_check.verify_profile"):
        with pytest.raises(feed_cmd.NoParserError):
            feed_cmd.feed(vault, input_arg=str(f))


def test_feed_empty_input_in_auto_mode_raises(tmp_path: Path) -> None:
    """Codex round 2 Finding I: empty input_arg in auto mode is a user error."""
    vault = _vault(tmp_path)
    with patch("clonemate.profile_check.verify_profile"):
        with pytest.raises(ValueError, match="non-empty"):
            feed_cmd.feed(vault, input_arg="")


def test_feed_finish_written_zero_logs_zero_count(tmp_path: Path) -> None:
    """Codex round 4 Finding F (MED): the `--written 0` path (Claude routed
    the prompt but wrote no wiki) is supported and produces a clear log entry."""
    import subprocess

    vault = _vault(tmp_path)
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
    feed_cmd.feed_finish(vault, written=0)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "feed" in log
    assert "+0 raw" in log


def test_emit_prompt_for_ingest_mentions_raw_paths(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    f = tmp_path / "note.md"
    f.write_text("# 笔记\n", encoding="utf-8")
    with patch("clonemate.profile_check.verify_profile"):
        result = feed_cmd.feed(vault, input_arg=str(f))
    prompt = feed_cmd.emit_prompt_for_ingest(vault, result=result)
    assert "feed" in prompt.lower()
    assert "incremental" in prompt.lower() or "增量" in prompt
    assert any(p in prompt for p in result.raw_paths)
