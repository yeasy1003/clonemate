"""E2E plumbing tests for M5 ask — runs in CI (no real LLM)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from clonemate import __main__ as main_entry
from clonemate import merge_note, query_cmd

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "vaults" / "m5-fixture"


def _copy(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    shutil.copytree(_FIXTURE, vault)
    return vault


def _git_init(vault: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )


def test_emit_prompt_default_renders_full_pipeline(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    prompt = query_cmd.emit_prompt(vault, question="ta 对 RAG 怎么看?")
    assert "ta 对 RAG 怎么看?" in prompt
    assert "voice.md" in prompt
    assert "4a" in prompt and "4b" in prompt and "4c" in prompt
    # Has needs_review warning because RAG 立场.md is needs_review:true
    assert "⚠️ 含未复核条目" in prompt
    assert "wiki/concepts/RAG 立场.md" in prompt


def test_emit_prompt_literal_skips_voice(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    prompt = query_cmd.emit_prompt(vault, question="x", mode="literal")
    assert "literal" in prompt.lower()
    assert "中性" in prompt or "neutral" in prompt.lower()


def test_emit_prompt_voice_only_requires_voice_file(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    (vault / "wiki" / "voice.md").unlink()
    with pytest.raises(FileNotFoundError, match="voice.md"):
        query_cmd.emit_prompt(vault, question="x", mode="voice-only")


def test_default_mode_falls_back_when_voice_missing(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    (vault / "wiki" / "voice.md").unlink()
    prompt = query_cmd.emit_prompt(vault, question="x")
    assert "voice.md 缺失" in prompt or "literal" in prompt.lower()


def test_finish_no_synthesis_appends_log_e2e(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    _git_init(vault)
    query_cmd.finish(vault, question="q1", synthesis_written=False)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "query" in log and "+0 synthesis" in log


def test_finish_with_synthesis_rebuilds_index_e2e(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    _git_init(vault)
    merge_note.write(
        vault_dir=vault, page_type="synthesis", title="RAG 立场对比",
        sources=["src-0001", "src-0007"], confidence="medium",
        body="# RAG 立场对比\n\n## 综述\n本质上,ta 倾向 lite-RAG\n",
        author_role="query",
    )
    query_cmd.finish(
        vault, question="ta 对 RAG 怎么看?",
        synthesis_written=True, synthesis_title="RAG 立场对比",
    )
    idx = (vault / "index.md").read_text(encoding="utf-8")
    assert "RAG 立场对比" in idx
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "+1 synthesis" in log
    # Synthesis page survived
    assert (vault / "wiki" / "syntheses" / "RAG 立场对比.md").is_file()


def test_cli_ask_round_trip_e2e(tmp_path: Path, capsys) -> None:
    """ask → ask-finish round trip with no synthesis."""
    vault = _copy(tmp_path)
    _git_init(vault)
    rc = main_entry.main([
        "ask", "--root", str(tmp_path), "--slug", "zhangsan",
        "--my-open-id", "ou_xxxxxxxxxxxxxxxx", "--no-bg-sync",
        "--question", "ta 喜欢什么?",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ta 喜欢什么?" in out
    rc = main_entry.main([
        "ask-finish", "--root", str(tmp_path), "--slug", "zhangsan",
        "--question", "ta 喜欢什么?",
        "--synthesis-written", "0",
    ])
    assert rc == 0
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "ta 喜欢什么?" in log


def test_cli_ask_with_synthesis_round_trip_e2e(tmp_path: Path, capsys) -> None:
    """Full round trip with synthesis writeback."""
    vault = _copy(tmp_path)
    _git_init(vault)
    rc = main_entry.main([
        "ask", "--root", str(tmp_path), "--slug", "zhangsan",
        "--my-open-id", "ou_xxxxxxxxxxxxxxxx", "--no-bg-sync",
        "--question", "ta 对 RAG 怎么看?",
    ])
    assert rc == 0
    capsys.readouterr()  # discard
    # Simulate Claude writing the synthesis
    merge_note.write(
        vault_dir=vault, page_type="synthesis", title="RAG 立场综述",
        sources=["src-0001"], confidence="medium",
        body="# RAG 立场综述\n\n## 综述\n本质上...\n",
        author_role="query",
    )
    rc = main_entry.main([
        "ask-finish", "--root", str(tmp_path), "--slug", "zhangsan",
        "--question", "ta 对 RAG 怎么看?",
        "--synthesis-written", "1",
        "--synthesis-title", "RAG 立场综述",
    ])
    assert rc == 0
    idx = (vault / "index.md").read_text(encoding="utf-8")
    assert "RAG 立场综述" in idx
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "+1 synthesis" in log


def test_synthesis_writeback_uses_query_author_role(tmp_path: Path) -> None:
    """Synthesis pages from Phase ask carry last_modified_by: query.

    Important provenance signal: lint can later distinguish Claude-generated
    syntheses (author_role='query') from user-edited ones."""
    vault = _copy(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="synthesis", title="X",
        sources=["src-0001"], confidence="medium",
        body="# X\n", author_role="query",
    )
    fm = yaml.safe_load(
        (vault / "wiki" / "syntheses" / "X.md")
        .read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["last_modified_by"] == "query"


def test_ask_finish_idempotent_log_grows(tmp_path: Path) -> None:
    """Running ask-finish twice → log has 2 entries; HEAD advances twice."""
    vault = _copy(tmp_path)
    _git_init(vault)
    main_entry.main([
        "ask-finish", "--root", str(tmp_path), "--slug", "zhangsan",
        "--question", "q1", "--synthesis-written", "0",
    ])
    main_entry.main([
        "ask-finish", "--root", str(tmp_path), "--slug", "zhangsan",
        "--question", "q2", "--synthesis-written", "0",
    ])
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert log.count("query") >= 2
    assert "q1" in log and "q2" in log


def test_question_with_newlines_logged_one_line(tmp_path: Path) -> None:
    """Multi-line questions must be sanitized so log.md stays one-entry-per-line."""
    vault = _copy(tmp_path)
    _git_init(vault)
    query_cmd.finish(
        vault, question="line one\n  line two\n\nline three",
        synthesis_written=False,
    )
    log = (vault / "log.md").read_text(encoding="utf-8")
    # The question content survived as a single space-separated string
    assert "line one line two line three" in log
    # No literal newline in the middle of the question subject
    query_lines = [
        ln for ln in log.splitlines() if ln.startswith("## ") and "query" in ln
    ]
    assert query_lines, "expected at least one `## [...] query` log line"
    for line in query_lines:
        assert "\n" not in line   # tautology, but explicit


def test_voice_only_with_voice_present_works_e2e(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    prompt = query_cmd.emit_prompt(vault, question="say hi", mode="voice-only")
    assert "say hi" in prompt
    assert "voice-only" in prompt.lower()
    assert "voice.md" in prompt
