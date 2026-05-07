"""Tests for ingest_cmd.py."""
from __future__ import annotations

from pathlib import Path

import yaml
from clonemate import ingest_cmd, merge_note, raw_writer


def _vault_with_raw(tmp_path: Path) -> Path:
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
    writer.write(
        raw_writer.RawCandidate(
            "im_1v1",
            "im_1v1/oc_x/2026-04.md",
            "im1",
            {"author_open_id": "ou_xxxxxxxxxxxxxxxx"},
            "> 你好",
        )
    )
    return v


def test_list_raw_groups_by_source_type(tmp_path: Path) -> None:
    vault = _vault_with_raw(tmp_path)
    grouped = ingest_cmd.list_raw(vault)
    assert set(grouped.keys()) == {"contact", "im_1v1"}
    assert all(isinstance(p, Path) for paths in grouped.values() for p in paths)
    assert len(grouped["contact"]) == 1
    assert len(grouped["im_1v1"]) == 1


def test_list_raw_skips_hidden_metadata_files(tmp_path: Path) -> None:
    vault = _vault_with_raw(tmp_path)
    # The writer leaves .hashes.txt + .src_id_counter; list_raw must skip them.
    grouped = ingest_cmd.list_raw(vault)
    for paths in grouped.values():
        for p in paths:
            assert not p.name.startswith(".")


def test_emit_prompt_contains_red_lines_and_inputs(tmp_path: Path) -> None:
    vault = _vault_with_raw(tmp_path)
    prompt = ingest_cmd.emit_prompt(vault)
    assert "target_open_id" in prompt
    assert "ou_xxxxxxxxxxxxxxxx" in prompt
    assert "张三" in prompt
    # Red-line phrases (anchored from prompt-ingest.md)
    assert "作者归属" in prompt
    assert "voice" in prompt
    # Source counts
    assert "contact" in prompt and "im_1v1" in prompt
    # References paths Claude should read
    assert "references/prompt-ingest.md" in prompt
    assert "references/workflow-ingest.md" in prompt


def test_finish_rebuilds_index_and_logs(tmp_path: Path) -> None:
    import subprocess

    vault = _vault_with_raw(tmp_path)
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
    # Pretend subagents have written some wiki pages
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="X",
        sources=["src-0001"],
        confidence="medium",
        body="# X\n",
        author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault,
        page_type="persona",
        title=None,
        sources=["src-0002"],
        confidence="medium",
        body="# 张三\n",
        author_role="ingest",
    )

    ingest_cmd.finish(vault, raw_count=2, wiki_count=2)

    assert (vault / "index.md").is_file()
    assert (vault / "log.md").is_file()
    log_text = (vault / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log_text
    assert "+2 raw / +2 wiki" in log_text


# ---------------------------------------------------------------------------
# Task 7: ingest_cmd.finish auto-commits vault (Codex round 3 Finding 9)
# ---------------------------------------------------------------------------


def test_ingest_finish_auto_commits_vault(tmp_path: Path, monkeypatch) -> None:
    """Codex round 3 Finding 9: ingest-finish must auto-commit so subsequent
    review can recover prior section bodies via git show."""
    import subprocess

    vault = _vault_with_raw(tmp_path)
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )

    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="medium",
        body="# X\n", author_role="ingest",
    )
    ingest_cmd.finish(vault, raw_count=1, wiki_count=1)
    log_text = subprocess.run(
        ["git", "log", "--oneline", "-5"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "ingest:" in log_text and "+1 raw / +1 wiki" in log_text


def test_ingest_finish_works_without_global_git_config(
    tmp_path: Path, monkeypatch,
) -> None:
    """Codex round 4 Finding 11: finish() must succeed even if global git
    user.name / user.email are not set — _auto_commit_vault uses a built-in
    identity fallback (`-c user.email=clonemate@local`)."""
    import subprocess

    vault = _vault_with_raw(tmp_path)
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    # Initial commit with explicit identity (so HEAD exists)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )
    # Now SIMULATE missing global config by pointing HOME to an empty tmp dir
    # so git won't find any user.email / user.name.
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Also unset XDG_CONFIG_HOME and any GIT_* identity overrides
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
              "GIT_COMMITTER_EMAIL", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(k, raising=False)

    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="medium",
        body="# X\n", author_role="ingest",
    )
    ingest_cmd.finish(vault, raw_count=1, wiki_count=1)
    # HEAD must have advanced (a real commit landed despite no global config)
    head_log = subprocess.run(
        ["git", "log", "--oneline", "-3"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "ingest:" in head_log


def test_ingest_finish_no_changes_is_idempotent(tmp_path: Path) -> None:
    """Calling finish() twice in a row when the second has no new changes
    must NOT raise (empty-diff detected pre-commit per Codex Finding 11)."""
    import subprocess

    vault = _vault_with_raw(tmp_path)
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="medium",
        body="# X\n", author_role="ingest",
    )
    ingest_cmd.finish(vault, raw_count=1, wiki_count=1)
    # Second finish — no new changes
    ingest_cmd.finish(vault, raw_count=1, wiki_count=1)   # must not raise
