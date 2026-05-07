"""Tests for forget_cmd — Level 1 / Level 2 / Level 3 forget operations."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from clonemate import forget_cmd, merge_note

_FILTER_REPO_AVAILABLE = shutil.which("git-filter-repo") is not None
_skip_no_filter_repo = pytest.mark.skipif(
    not _FILTER_REPO_AVAILABLE, reason="git-filter-repo not installed",
)


def _vault(root: Path, slug: str) -> Path:
    """Build a minimal vault with `_clone.yaml` and `wiki/` scaffolding."""
    vault = root / slug
    (vault / "raw").mkdir(parents=True)
    (vault / "raw" / "im_1v1").mkdir(parents=True, exist_ok=True)
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
                "display_name": slug,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return vault


def test_forget_level1_requires_yes(tmp_path: Path) -> None:
    """Without --yes, forget_level1 raises (avoid accidental nukes)."""
    root = tmp_path / "files" / "clonemate"
    _vault(root, "zhangsan")
    with pytest.raises(forget_cmd.ConfirmationRequiredError):
        forget_cmd.forget_level1(root, "zhangsan")


def test_forget_level1_with_yes_removes_vault(tmp_path: Path) -> None:
    root = tmp_path / "files" / "clonemate"
    vault = _vault(root, "zhangsan")
    forget_cmd.forget_level1(root, "zhangsan", yes=True)
    assert not vault.exists()


def test_forget_level1_writes_tomb_marker(tmp_path: Path) -> None:
    """A tomb marker (slug only, no content) must persist outside the vault."""
    root = tmp_path / "files" / "clonemate"
    _vault(root, "zhangsan")
    forget_cmd.forget_level1(root, "zhangsan", yes=True)
    tombs = list((root / ".forget-tombs").iterdir())
    assert tombs, "expected tomb marker"
    contents = tombs[0].read_text(encoding="utf-8")
    assert "zhangsan" in contents
    assert "ou_" not in contents  # no identity content leaked


def test_forget_level1_unknown_slug_raises(tmp_path: Path) -> None:
    root = tmp_path / "files" / "clonemate"
    root.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="zhangsan"):
        forget_cmd.forget_level1(root, "zhangsan", yes=True)


# ---------------------------------------------------------------------------
# Task 11: identify_dirty_pages
# ---------------------------------------------------------------------------


def test_identify_dirty_pages_finds_pages_referencing_source(tmp_path: Path) -> None:
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0001", "src-0002"], confidence="medium",
        body="# A\n", author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="B",
        sources=["src-0002"], confidence="medium",
        body="# B\n", author_role="ingest",
    )
    out = forget_cmd.identify_dirty_pages(vault, source="src-0001")
    relpaths = [p.page_relpath for p in out]
    assert "wiki/entities/A.md" in relpaths
    assert "wiki/entities/B.md" not in relpaths


def test_identify_dirty_pages_empty_when_no_match(tmp_path: Path) -> None:
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0001"], confidence="medium",
        body="# A\n", author_role="ingest",
    )
    assert forget_cmd.identify_dirty_pages(vault, source="src-9999") == []


# ---------------------------------------------------------------------------
# Task 12: pinned_fields_audit
# ---------------------------------------------------------------------------


def test_pinned_fields_audit_clears_pins_when_sourceless(tmp_path: Path) -> None:
    """Page with only the dropped source → unpin all + needs_review=True
    (regardless of body content; body rewrite happens later by Claude)."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=["src-0013"], confidence="high",
        body="# 张三\n\n## 职责\n后端\n", author_role="ingest",
        pinned_fields=["职责", "沟通偏好"],
    )
    forget_cmd.pinned_fields_audit(vault, source="src-0013")
    fm = yaml.safe_load(
        (vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["pinned_fields"] == []
    assert fm["needs_review"] is True


def test_pinned_fields_audit_demotes_confidence_when_sources_shrink(tmp_path: Path) -> None:
    """Page with src-0013 + src-0014 → drop src-0013 → confidence -1 + needs_review,
    pinned_fields preserved."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0013", "src-0014"], confidence="high",
        body="# X\n\n## 概述\nv1\n", author_role="ingest",
        pinned_fields=["概述"],
    )
    forget_cmd.pinned_fields_audit(vault, source="src-0013")
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["confidence"] == "medium"
    assert fm["needs_review"] is True
    assert fm["pinned_fields"] == ["概述"]


def test_pinned_fields_audit_low_stays_low(tmp_path: Path) -> None:
    """confidence=low can't be demoted further; stays low + needs_review."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0013", "src-0014"], confidence="low",
        body="# X\n", author_role="ingest",
    )
    forget_cmd.pinned_fields_audit(vault, source="src-0013")
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["confidence"] == "low"
    assert fm["needs_review"] is True


def test_pinned_fields_audit_skips_pages_not_referencing_source(tmp_path: Path) -> None:
    """Pages whose sources don't include the dropped src are untouched."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0001"], confidence="high",
        body="# X\n", author_role="ingest",
        pinned_fields=["概述"],
    )
    forget_cmd.pinned_fields_audit(vault, source="src-9999")
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["confidence"] == "high"  # untouched
    assert fm["pinned_fields"] == ["概述"]


def test_pinned_fields_audit_raises_when_voice_references_source(tmp_path: Path) -> None:
    """Codex round 1 Finding 7: voice.md is read-only from forget.
    The audit refuses to mutate it and tells the user to re-ingest."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    (vault / "wiki" / "voice.md").write_text(
        "---\npage_type: voice\nsources: [src-0013]\nconfidence: high\n"
        "few_shot_count: 6\n---\n\n# 总体基调\n",
        encoding="utf-8",
    )
    with pytest.raises(forget_cmd.VoiceReferencesForgottenSourceError, match="src-0013"):
        forget_cmd.pinned_fields_audit(vault, source="src-0013")


def test_pinned_fields_audit_updates_last_modified(tmp_path: Path) -> None:
    """Codex round 1 Finding 11: timestamp + author_role refresh on mutation."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0013", "src-0014"], confidence="high",
        body="# X\n", author_role="ingest",
    )
    forget_cmd.pinned_fields_audit(vault, source="src-0013")
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["last_modified_by"] == "user"
    assert fm["last_modified"]   # not empty


# ---------------------------------------------------------------------------
# Task 13: forget_level2_start
# ---------------------------------------------------------------------------


def test_forget_level2_start_saves_state_and_marks_dirty(tmp_path: Path) -> None:
    """Codex round 1 Findings 2+4+6: durable state + dirty markers + raw snippets."""
    from clonemate import forget_state
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    raw_file = vault / "raw" / "im_1v1" / "src-0013.md"
    raw_file.write_text(
        "---\nsrc_id: src-0013\n---\n# raw\n张三 said: lite-RAG 更适合短上下文\n",
        encoding="utf-8",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0013"], confidence="high",
        body="# A\n", author_role="ingest",
        pinned_fields=["概述"],
    )
    prompt = forget_cmd.forget_level2_start(vault, source="src-0013")
    # Raw deleted
    assert not raw_file.exists()
    # State saved with raw snippets
    state = forget_state.load(vault, source="src-0013")
    assert state is not None
    assert state.source == "src-0013"
    assert state.dirty_pages == ["wiki/entities/A.md"]
    assert state.raw_snippets   # non-empty — captured before deletion
    # Page has forget_dirty marker
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "A.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm.get("forget_dirty") == "src-0013"
    assert fm["needs_review"] is True
    # Prompt mentions the src and the dirty page
    assert "src-0013" in prompt
    assert "wiki/entities/A.md" in prompt


def test_forget_level2_start_raises_when_raw_and_state_both_missing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    with pytest.raises(FileNotFoundError, match="src-9999"):
        forget_cmd.forget_level2_start(vault, source="src-9999")


def test_forget_level2_start_idempotent_when_state_exists(tmp_path: Path) -> None:
    """Codex round 1 Finding 6: re-running start after a crash (raw deleted,
    state saved, prompt was emitted but never finished) must not raise.
    Re-emits the prompt from saved state."""
    from clonemate import forget_state
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    raw_file = vault / "raw" / "im_1v1" / "src-0013.md"
    raw_file.write_text(
        "---\nsrc_id: src-0013\n---\n# raw\nsnippet\n",
        encoding="utf-8",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0013"], confidence="high",
        body="# A\n", author_role="ingest",
    )
    # First call — normal path
    forget_cmd.forget_level2_start(vault, source="src-0013")
    # Second call — raw is gone, but state exists → re-emit
    prompt_second = forget_cmd.forget_level2_start(vault, source="src-0013")
    assert "src-0013" in prompt_second
    assert "wiki/entities/A.md" in prompt_second
    # State unchanged across re-runs
    state = forget_state.load(vault, source="src-0013")
    assert state and state.source == "src-0013"


def test_forget_level2_start_aborts_when_voice_references_source(tmp_path: Path) -> None:
    """Codex round 1 Finding 7: voice references → abort, raw NOT deleted."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    raw_file = vault / "raw" / "im_1v1" / "src-0013.md"
    raw_file.write_text(
        "---\nsrc_id: src-0013\n---\n# raw\n", encoding="utf-8",
    )
    (vault / "wiki" / "voice.md").write_text(
        "---\npage_type: voice\nsources: [src-0013]\nconfidence: high\n"
        "few_shot_count: 6\n---\n\n# 总体基调\n",
        encoding="utf-8",
    )
    with pytest.raises(forget_cmd.VoiceReferencesForgottenSourceError):
        forget_cmd.forget_level2_start(vault, source="src-0013")
    # Raw still intact — voice abort happens BEFORE delete
    assert raw_file.exists()


# ---------------------------------------------------------------------------
# Task 14: forget_level2_finish (filter-repo path)
# ---------------------------------------------------------------------------


@_skip_no_filter_repo
def test_forget_level2_finish_scrubs_source_id_and_snippets(tmp_path: Path) -> None:
    """Codex round 1 Finding 4: filter-repo scrubs both src_id literal AND
    raw content snippets captured during start."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    raw = vault / "raw" / "im_1v1" / "src-0013.md"
    secret = "PROPRIETARY_LITE_RAG_DETAILS"
    raw.write_text(
        f"---\nsrc_id: src-0013\n---\n# raw\nThe project uses {secret} extensively\n",
        encoding="utf-8",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0013"], confidence="high",
        body=f"# A\n## 概述\nThe project uses {secret} extensively (per src-0013)\n",
        author_role="ingest",
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "ingest"], cwd=vault, check=True,
    )
    forget_cmd.forget_level2_start(vault, source="src-0013")
    # Claude rewrites — uses forget_rewrite (clears forget_dirty marker, replaces sources)
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="A",
        sources=[], confidence="low", needs_review=True,
        body="# A\n## (page contents removed by forget)\n",
    )
    forget_cmd.forget_level2_finish(vault, source="src-0013")
    # Both content (-p) AND commit messages (--format=%B) are clean
    content_log = subprocess.run(
        ["git", "log", "-p", "--all"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout
    msg_log = subprocess.run(
        ["git", "log", "--all", "--format=%B"], cwd=vault,
        capture_output=True, text=True, check=True,
    ).stdout
    # 1. src_id literal scrubbed from BOTH content AND messages (Codex F05)
    assert "src-0013" not in content_log
    assert "src-0013" not in msg_log
    # 2. content snippet scrubbed too (Codex F04)
    assert secret not in content_log
    # 3. Live wiki shows post-rewrite content (no src-0013)
    a_text = (vault / "wiki" / "entities" / "A.md").read_text(encoding="utf-8")
    assert "src-0013" not in a_text
    # 4. State cleared (Codex F02)
    from clonemate import forget_state
    assert forget_state.load(vault, source="src-0013") is None


@_skip_no_filter_repo
def test_forget_level2_finish_aborts_when_dirty_marker_remains(tmp_path: Path) -> None:
    """Codex round 1 Finding 1: preflight refuses to scrub when wiki still
    has forget_dirty markers (Claude didn't finish)."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    raw = vault / "raw" / "im_1v1" / "src-0013.md"
    raw.write_text("---\nsrc_id: src-0013\n---\n# raw\n", encoding="utf-8")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0013"], confidence="high",
        body="# A\n", author_role="ingest",
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "ingest"], cwd=vault, check=True,
    )
    forget_cmd.forget_level2_start(vault, source="src-0013")
    # Skip Claude rewrite — forget_dirty marker still present
    with pytest.raises(forget_cmd.ForgetIncompleteError, match="forget_dirty"):
        forget_cmd.forget_level2_finish(vault, source="src-0013")


@_skip_no_filter_repo
def test_forget_level2_finish_aborts_when_body_has_inline_citation(tmp_path: Path) -> None:
    """Codex round 4 Issue-G (MED): preflight scans body content too. If
    Claude's rewrite removed the source from frontmatter but left an inline
    citation in body, finish must abort (filter-repo would silently rewrite
    the live blob)."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    raw = vault / "raw" / "im_1v1" / "src-0013.md"
    raw.write_text("---\nsrc_id: src-0013\n---\n# raw\n", encoding="utf-8")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0013"], confidence="high",
        body="# A\n", author_role="ingest",
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "ingest"], cwd=vault, check=True,
    )
    forget_cmd.forget_level2_start(vault, source="src-0013")
    # User does forget_rewrite (drops source from frontmatter, clears forget_dirty),
    # but accidentally leaves "src-0013" inline in body
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="A",
        sources=[], confidence="low", needs_review=True,
        body="# A\n## (was supported by src-0013, content removed)\n",
    )
    with pytest.raises(forget_cmd.ForgetIncompleteError, match="body still contains"):
        forget_cmd.forget_level2_finish(vault, source="src-0013")


@_skip_no_filter_repo
def test_forget_level2_finish_aborts_when_source_still_in_frontmatter(tmp_path: Path) -> None:
    """Even if forget_dirty markers are gone (manual cleanup), fail if any
    page still lists the source in frontmatter."""
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    raw = vault / "raw" / "im_1v1" / "src-0013.md"
    raw.write_text("---\nsrc_id: src-0013\n---\n# raw\n", encoding="utf-8")
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0013"], confidence="high",
        body="# A\n", author_role="ingest",
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "ingest"], cwd=vault, check=True,
    )
    forget_cmd.forget_level2_start(vault, source="src-0013")
    # User manually clears forget_dirty but doesn't fix sources
    page = vault / "wiki" / "entities" / "A.md"
    text = page.read_text(encoding="utf-8")
    page.write_text(text.replace("forget_dirty: src-0013\n", ""), encoding="utf-8")
    with pytest.raises(forget_cmd.ForgetIncompleteError, match="src-0013"):
        forget_cmd.forget_level2_finish(vault, source="src-0013")


# ---------------------------------------------------------------------------
# Task 15: forget_level3_hard
# ---------------------------------------------------------------------------


def test_forget_level3_requires_strong_confirmation(tmp_path: Path) -> None:
    """Without yes_i_mean_it=True, refuses."""
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    with pytest.raises(forget_cmd.ConfirmationRequiredError):
        forget_cmd.forget_level3_hard(root, "zhangsan")
    with pytest.raises(forget_cmd.ConfirmationRequiredError):
        forget_cmd.forget_level3_hard(root, "zhangsan", yes_i_mean_it=False)


def test_forget_level3_with_strong_confirmation_removes_vault(tmp_path: Path) -> None:
    root = tmp_path / "root"
    vault = _vault(root, "zhangsan")
    forget_cmd.forget_level3_hard(root, "zhangsan", yes_i_mean_it=True)
    assert not vault.exists()
    tombs = list((root / ".forget-tombs").iterdir())
    assert tombs
