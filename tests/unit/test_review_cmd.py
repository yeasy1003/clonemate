"""Tests for review_cmd.py."""
from __future__ import annotations

from pathlib import Path

import yaml
from clonemate import merge_note, review_cmd


def test_review_checklist_dataclass_smoke() -> None:
    cl = review_cmd.ReviewChecklist(
        conflicts=[],
        needs_review_pages=[],
        ambiguities=[],
        unclear_topics=[],
    )
    assert cl.is_empty() is True
    assert cl.total_items() == 0


def test_review_checklist_total_counts_all_buckets() -> None:
    cl = review_cmd.ReviewChecklist(
        conflicts=[review_cmd.ConflictItem(page_relpath="wiki/entities/X.md", section_name="概述", body_excerpt="x")],
        needs_review_pages=[
            review_cmd.NeedsReviewItem(
                page_relpath="wiki/persona.md",
                title="张三",
                confidence="low",
                sources=["src-1"],
                pinned_fields=[],
            ),
        ],
        ambiguities=[
            review_cmd.AmbiguityItem(
                page_relpath="wiki/entities/X.md",
                description="X 项目歧义",
                body_excerpt="...",
            ),
        ],
        unclear_topics=[
            review_cmd.UnclearTopicItem(
                page_relpath="wiki/concepts/RAG.md",
                topic="RAG 立场",
                body_excerpt="...",
            ),
        ],
    )
    assert cl.is_empty() is False
    assert cl.total_items() == 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vault_with_wiki(tmp_path: Path) -> Path:
    v = tmp_path / "zhangsan"
    (v / "wiki" / "entities").mkdir(parents=True)
    (v / "wiki" / "concepts").mkdir(parents=True)
    (v / "wiki" / "syntheses").mkdir(parents=True)
    (v / "wiki" / "sources").mkdir(parents=True)
    return v


# ---------------------------------------------------------------------------
# Task 2: scan_conflicts
# ---------------------------------------------------------------------------


def test_scan_conflicts_finds_inline_marker(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    # Write a page with a conflict marker inside an H2 section
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="XX 项目",
        sources=["src-1"],
        confidence="medium",
        body=(
            "# XX 项目\n\n"
            "## 概述\n初始 v1\n\n> ⚠️ CONFLICT: section `概述` rewritten by ingest.\n\n"
            "## 协作画像\nD 视角\n"
        ),
        author_role="ingest",
    )
    conflicts = review_cmd.scan_conflicts(vault)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.page_relpath == "wiki/entities/XX 项目.md"
    assert c.section_name == "概述"
    assert "CONFLICT" in c.body_excerpt


def test_scan_conflicts_empty_when_no_marker(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="X",
        sources=[],
        confidence="medium",
        body="# X\n\n## 概述\n无冲突\n",
        author_role="ingest",
    )
    assert review_cmd.scan_conflicts(vault) == []


# ---------------------------------------------------------------------------
# Task 3: scan_needs_review
# ---------------------------------------------------------------------------


def test_scan_needs_review_finds_marked_pages(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault,
        page_type="persona",
        title=None,
        sources=["src-1"],
        confidence="low",
        needs_review=True,
        body="# 张三\n\n## 职责\n后端\n",
        author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="X",
        sources=["src-1"],
        confidence="high",
        needs_review=False,
        body="# X\n",
        author_role="ingest",
    )
    items = review_cmd.scan_needs_review(vault)
    assert len(items) == 1
    p = items[0]
    assert p.page_relpath == "wiki/persona.md"
    assert p.confidence == "low"
    assert "src-1" in p.sources


# ---------------------------------------------------------------------------
# Task 4: scan_ambiguities + scan_unclear_topics
# ---------------------------------------------------------------------------


def test_scan_ambiguities(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="X 项目",
        sources=["src-1"],
        confidence="medium",
        body="# X\n\n## 概述\n描述\n\n> ⚠️ AMBIGUOUS: X 项目可能指代码内部的 X-service 也可能指公开开源项目 X\n",
        author_role="ingest",
    )
    items = review_cmd.scan_ambiguities(vault)
    assert len(items) == 1
    a = items[0]
    assert a.page_relpath == "wiki/entities/X 项目.md"
    assert "X-service" in a.description


def test_scan_unclear_topics(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault,
        page_type="concept",
        title="RAG 立场",
        sources=["src-1"],
        confidence="low",
        body="# RAG\n\n> ⚠️ UNCLEAR: RAG 在 5 个 chat 中频繁出现但 ta 立场未明\n",
        author_role="ingest",
    )
    items = review_cmd.scan_unclear_topics(vault)
    assert len(items) == 1
    u = items[0]
    assert u.topic.startswith("RAG")


# ---------------------------------------------------------------------------
# Task 5: build_checklist
# ---------------------------------------------------------------------------


def test_build_checklist_aggregates_all_scanners(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault,
        page_type="persona",
        title=None,
        sources=["src-1"],
        confidence="low",
        needs_review=True,
        body="# 张三\n\n## 职责\n模糊\n\n> ⚠️ AMBIGUOUS: 职责说法不一\n",
        author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="X",
        sources=["src-1"],
        confidence="medium",
        body="# X\n\n## 概述\nv2\n\n> ⚠️ CONFLICT: section `概述` rewritten by ingest.\n\n> ⚠️ UNCLEAR: 角色边界\n",
        author_role="ingest",
    )
    cl = review_cmd.build_checklist(vault)
    assert cl.total_items() >= 4  # 1 conflict + 1 needs_review + 1 ambiguity + 1 unclear
    assert any(c.section_name == "概述" for c in cl.conflicts)
    assert any(p.page_relpath == "wiki/persona.md" for p in cl.needs_review_pages)
    assert cl.ambiguities and cl.ambiguities[0].description.startswith("职责")
    assert cl.unclear_topics and cl.unclear_topics[0].topic.startswith("角色")


# ---------------------------------------------------------------------------
# Task 6: emit_prompt
# ---------------------------------------------------------------------------


def test_emit_prompt_contains_buckets_and_red_lines(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan",
        "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx", "app_id": "cli_xxxxxxxxxxxxxxxx"},
        "display_name": "张三", "profile": "claude-code",
    }, allow_unicode=True), encoding="utf-8")
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=["src-1"], confidence="low", needs_review=True,
        body="# 张三\n\n## 职责\n后端\n", author_role="ingest",
    )
    prompt = review_cmd.emit_prompt(vault)
    assert "张三" in prompt
    assert "ou_xxxxxxxxxxxxxxxx" in prompt
    assert "references/prompt-review.md" in prompt
    assert "wiki/persona.md" in prompt
    assert "needs_review" in prompt
    # Red-line phrase
    assert "用户随时退出" in prompt or "skip" in prompt.lower()


def test_emit_prompt_when_empty_says_nothing_to_review(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "x", "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx",
        "app_id": "cli_xxxxxxxxxxxxxxxx"}, "display_name": "X",
        "profile": "claude-code",
    }, allow_unicode=True), encoding="utf-8")
    prompt = review_cmd.emit_prompt(vault)
    assert "no items" in prompt.lower() or "无需复核" in prompt


# ---------------------------------------------------------------------------
# Task 7: finish — rebuild index + log + auto-commit
# ---------------------------------------------------------------------------


def test_finish_writes_log_and_rebuilds_index(tmp_path: Path) -> None:
    import subprocess

    vault = _vault_with_wiki(tmp_path)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan", "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx",
        "app_id": "cli_xxxxxxxxxxxxxxxx"}, "display_name": "张三",
        "profile": "claude-code",
    }, allow_unicode=True), encoding="utf-8")
    # Initialize a git repo so _auto_commit_vault has somewhere to commit.
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
        body="# X\n", author_role="user",
    )
    review_cmd.finish(vault, resolved=3, skipped=2)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "review" in log
    assert "+3 resolved / +2 skipped" in log
    assert (vault / "index.md").is_file()
