"""Unit tests for query_cmd — Phase ask orchestration."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from clonemate import merge_note, query_cmd


def _git_init_vault(vault: Path) -> None:
    """Initialize the vault as a git repo so finish() can auto-commit."""
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )


def _vault_with_wiki(tmp_path: Path) -> Path:
    """A minimal but realistic vault: _clone.yaml + voice + persona + 1 entity."""
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
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
    # voice page
    (vault / "wiki" / "voice.md").write_text(
        "---\npage_type: voice\nsources: [src-1]\nfew_shot_count: 6\n"
        "confidence: high\n---\n\n# 总体基调\n简洁 / 偏理性\n",
        encoding="utf-8",
    )
    # persona page
    merge_note.write(
        vault_dir=vault,
        page_type="persona",
        title=None,
        sources=["src-1"],
        confidence="medium",
        body="# 张三\n\n## 职责\n后端\n",
        author_role="ingest",
    )
    # one entity
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="XX 项目",
        sources=["src-7"],
        confidence="medium",
        body="# XX 项目\n\n## 概述\n内部工具\n",
        author_role="ingest",
    )
    return vault


def test_emit_prompt_default_mode_contains_4a4b4c_steps(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    prompt = query_cmd.emit_prompt(vault, question="ta 对 RAG 的看法?")
    # Identity surfaces
    assert "张三" in prompt
    assert "ou_xxxxxxxxxxxxxxxx" in prompt
    # Question echoed
    assert "ta 对 RAG 的看法?" in prompt
    # All 4 query phases referenced
    assert "4a" in prompt and "4b" in prompt and "4c" in prompt
    # Voice transfer is ON in default mode
    assert "voice.md" in prompt
    assert "voice transfer" in prompt.lower()
    # Disclaimer template included
    assert "语气模仿 ta 但非 ta 本人" in prompt
    # Reference to prompt-query
    assert "references/prompt-query.md" in prompt
    # Finish command
    assert "ask-finish" in prompt
    # Red lines mention 事实正确 + 作者归属
    assert "事实正确" in prompt or "事实不漂移" in prompt
    assert "作者归属" in prompt or "author_open_id" in prompt


def test_emit_prompt_literal_mode_skips_voice_transfer(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    prompt = query_cmd.emit_prompt(
        vault, question="What is RAG?", mode="literal",
    )
    # Question + identity still present
    assert "What is RAG?" in prompt
    assert "张三" in prompt
    # Mode is announced
    assert "literal" in prompt.lower()
    # Voice transfer is OFF — explicit instruction
    assert (
        "skip voice" in prompt.lower()
        or "do not voice" in prompt.lower()
        or "不进行 voice transfer" in prompt
        or "no voice transfer" in prompt.lower()
    )
    # The default-mode 4b voice-rewrite call MUST NOT be the active step:
    #   either 4b is omitted, or it's explicitly marked skipped.
    assert prompt.count("voice transfer") == 0 or "skip" in prompt.lower()
    # 4a (facts) and 4c (disclaimer) still present
    assert "4a" in prompt and "4c" in prompt
    # Disclaimer for literal mode does NOT claim voice mimicry
    assert (
        "中性事实" in prompt
        or "不模仿 ta 语气" in prompt
        or "neutral" in prompt.lower()
    )
    # voice.md is NOT in the candidate list for literal mode
    assert "voice.md" not in prompt or "do not read voice.md" in prompt.lower()


def test_emit_prompt_voice_only_mode_prioritizes_style(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    prompt = query_cmd.emit_prompt(
        vault, question="说两句", mode="voice-only",
    )
    assert "说两句" in prompt
    assert "voice-only" in prompt.lower()
    assert "voice.md" in prompt  # 4b is on
    # Voice-only explicitly says style > facts (relative)
    assert "风格" in prompt or "style" in prompt.lower()
    assert (
        "事实可降级" in prompt
        or "fact completeness is secondary" in prompt.lower()
        or "罕用" in prompt
    )
    # Disclaimer present
    assert "语气模仿 ta 但非 ta 本人" in prompt
    # Even in voice-only, 事实不漂移 is still a red line — voice ≠ fabrication
    assert "事实不漂移" in prompt or "无 source 支撑" in prompt


def test_emit_prompt_warns_when_needs_review_pages_exist(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    # Add a needs_review concept page
    merge_note.write(
        vault_dir=vault,
        page_type="concept",
        title="RAG 立场",
        sources=["src-1"],
        confidence="low",
        needs_review=True,
        body="# RAG 立场\n\n推断:可能更看好 lite-RAG\n",
        author_role="ingest",
    )
    prompt = query_cmd.emit_prompt(vault, question="ta 对 RAG 的看法?")
    # Warning instruction surfaces
    assert "⚠️ 含未复核条目" in prompt or "含未复核" in prompt
    # The needs_review page is listed by relpath
    assert "wiki/concepts/RAG 立场.md" in prompt
    # Tells Claude to append the warning when citing such pages
    assert "needs_review" in prompt


def test_emit_prompt_no_warning_when_no_needs_review_pages(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    prompt = query_cmd.emit_prompt(vault, question="anything")
    # No `needs_review` page list block
    # (We accept the *word* needs_review may appear in red-line text; what we assert
    #  is that the explicit page-listing block is absent.)
    assert "⚠️ 含未复核条目" not in prompt


def test_emit_prompt_default_mode_falls_back_when_voice_missing(
    tmp_path: Path,
) -> None:
    vault = _vault_with_wiki(tmp_path)
    (vault / "wiki" / "voice.md").unlink()  # remove voice page
    prompt = query_cmd.emit_prompt(vault, question="anything")
    # Tells Claude to degrade to literal-style behavior
    assert (
        "voice.md 缺失" in prompt
        or "voice.md missing" in prompt.lower()
        or "no voice page" in prompt.lower()
    )
    assert (
        "literal" in prompt.lower()
        or "neutral" in prompt.lower()
        or "中性" in prompt
    )
    # No crash, prompt still mentions question
    assert "anything" in prompt


@pytest.mark.parametrize(
    "scenario,setup",
    [
        ("empty_file", lambda p: p.write_text("", encoding="utf-8")),
        (
            "malformed_yaml",
            lambda p: p.write_text(
                "---\nnot: valid: yaml: [{\n---\n# x\n", encoding="utf-8",
            ),
        ),
        (
            "wrong_page_type",
            lambda p: p.write_text(
                "---\npage_type: persona\nsources: [src-1]\nconfidence: medium\n---\n# x\n",
                encoding="utf-8",
            ),
        ),
        (
            "frontmatter_not_dict",
            lambda p: p.write_text(
                "---\n- a\n- b\n---\n# x\n", encoding="utf-8",
            ),
        ),
    ],
)
def test_emit_prompt_default_falls_back_when_voice_invalid(
    tmp_path: Path, scenario: str, setup,
) -> None:
    """Codex round 1 Finding 5 + round 2 expansion: voice.md presence is not
    enough — must parse as valid yaml dict with page_type: voice. Each
    invalid sub-case triggers the same fallback as a missing file."""
    vault = _vault_with_wiki(tmp_path)
    setup(vault / "wiki" / "voice.md")
    prompt = query_cmd.emit_prompt(vault, question="x")
    assert (
        "voice.md 缺失" in prompt
        or "voice.md missing" in prompt.lower()
        or "literal" in prompt.lower()
        or "中性" in prompt
    ), f"default mode must degrade for {scenario!r}"


@pytest.mark.parametrize(
    "scenario,setup",
    [
        ("missing", lambda p: p.unlink()),
        ("empty_file", lambda p: p.write_text("", encoding="utf-8")),
        (
            "malformed_yaml",
            lambda p: p.write_text(
                "---\nnot: valid: yaml: [{\n---\n# x\n", encoding="utf-8",
            ),
        ),
        (
            "wrong_page_type",
            lambda p: p.write_text(
                "---\npage_type: persona\nsources: [src-1]\nconfidence: medium\n---\n# x\n",
                encoding="utf-8",
            ),
        ),
    ],
)
def test_emit_prompt_voice_only_raises_when_voice_invalid(
    tmp_path: Path, scenario: str, setup,
) -> None:
    """Codex round 1 Finding 5 + round 2 expansion: voice-only mode treats
    every kind of unusable voice.md as fatal — the user explicitly asked for
    voice, degrading silently is wrong."""
    vault = _vault_with_wiki(tmp_path)
    setup(vault / "wiki" / "voice.md")
    with pytest.raises(FileNotFoundError, match="voice.md"):
        query_cmd.emit_prompt(vault, question="x", mode="voice-only")


def test_emit_prompt_literal_mode_works_without_voice(tmp_path: Path) -> None:
    """literal mode never reads voice.md, so its absence is fine."""
    vault = _vault_with_wiki(tmp_path)
    (vault / "wiki" / "voice.md").unlink()
    prompt = query_cmd.emit_prompt(vault, question="x", mode="literal")
    assert "x" in prompt
    assert "voice.md" not in prompt or "do not read" in prompt.lower()


# --- Task 6: finish writes log + auto-commits (no synthesis path) ---


def test_finish_writes_log_no_synthesis(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    _git_init_vault(vault)
    query_cmd.finish(
        vault, question="ta 对 RAG 的看法?",
        synthesis_written=False, synthesis_title=None,
    )
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "query" in log
    assert "ta 对 RAG 的看法?" in log
    assert "+0 synthesis" in log


def test_finish_rejects_synthesis_written_without_title(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    _git_init_vault(vault)
    with pytest.raises(ValueError, match="synthesis_title"):
        query_cmd.finish(
            vault, question="x",
            synthesis_written=True, synthesis_title=None,
        )


# --- Task 7: finish writes synthesis path → rebuilds index ---


def test_finish_rebuilds_index_when_synthesis_written(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    _git_init_vault(vault)
    # Pretend Claude wrote a synthesis page mid-conversation
    merge_note.write(
        vault_dir=vault, page_type="synthesis", title="RAG 立场对比",
        sources=["src-1", "src-7"], confidence="medium",
        body="# RAG 立场对比\n\n## 综述\nta 倾向 lite-RAG\n",
        author_role="query",
    )
    query_cmd.finish(
        vault, question="ta 对 RAG 的看法?",
        synthesis_written=True, synthesis_title="RAG 立场对比",
    )
    idx = (vault / "index.md").read_text(encoding="utf-8")
    # Index now lists the synthesis under 🔗 Syntheses
    assert "RAG 立场对比" in idx
    assert "syntheses/RAG 立场对比.md" in idx
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "+1 synthesis" in log
    assert "RAG 立场对比" in log


# --- Task 8: finish auto-commit semantics ---


def test_finish_auto_commits_query_state(tmp_path: Path) -> None:
    """Codex round 3 Finding 9 — query finish must auto-commit so subsequent
    review can recover prior state via git history."""
    vault = _vault_with_wiki(tmp_path)
    _git_init_vault(vault)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    query_cmd.finish(
        vault, question="x", synthesis_written=False,
    )
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head_after != head_before, "finish() must advance HEAD"
    log_one = subprocess.run(
        ["git", "log", "--oneline", "-1"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "query:" in log_one


def test_finish_idempotent_when_no_changes(tmp_path: Path) -> None:
    """Calling finish twice in a row when the second adds no new content
    must not raise (empty-diff detected pre-commit per Codex Finding 11).

    NB: log_append actually mutates log.md every call, so a 'true no-op'
    would only be possible if log_append also became idempotent. Until then,
    the second finish() lands a real follow-up commit. This test asserts
    that NEITHER call raises and HEAD has advanced both times.
    """
    vault = _vault_with_wiki(tmp_path)
    _git_init_vault(vault)
    query_cmd.finish(vault, question="q1", synthesis_written=False)
    head1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    query_cmd.finish(vault, question="q2", synthesis_written=False)
    head2 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head1 != head2, "two distinct finish() calls → two commits"


def test_finish_works_without_global_git_config(tmp_path: Path, monkeypatch) -> None:
    """Identity fallback (Codex Finding 11): finish must succeed even with
    no global git user.name / user.email."""
    vault = _vault_with_wiki(tmp_path)
    _git_init_vault(vault)
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
              "GIT_COMMITTER_EMAIL", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(k, raising=False)
    query_cmd.finish(vault, question="q", synthesis_written=False)
    head_log = subprocess.run(
        ["git", "log", "--oneline", "-1"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "query:" in head_log


def test_auto_commit_vault_empty_diff_path_is_no_op(tmp_path: Path) -> None:
    """Codex round 1 Finding 10: explicitly exercise the empty-diff path of
    `_auto_commit_vault` to make sure the round-4 finding (cp.returncode == 0
    short-circuits silently) still holds. Query's normal flow always mutates
    log.md so the empty-diff branch never fires from finish — this test calls
    the helper directly."""
    from clonemate import git_ops
    vault = _vault_with_wiki(tmp_path)
    _git_init_vault(vault)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    # Call helper directly with no pending changes — must NOT raise, must NOT commit.
    git_ops._auto_commit_vault(vault, message="should-not-commit")
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head_after == head_before, (
        "_auto_commit_vault must short-circuit when there is nothing to commit"
    )
