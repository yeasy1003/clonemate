"""review_cmd — Phase B/C orchestrator.

Phase B (this module):
  - Read vault wiki/, scan for review-worthy items
  - Emit a ReviewChecklist + a prompt for Claude main conversation

Phase C (Claude main conversation, driven by references/prompt-review.md):
  - For each item in the checklist, ask the user (4-option choice)
  - Apply the decision via merge_note.write / pin / resolve_conflict
  - Skip items the user defers; they remain `[需复核]` (not blocking)

This module DOES NOT call any LLM (spec §4.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConflictItem:
    page_relpath: str  # e.g. "wiki/entities/XX 项目.md"
    section_name: str  # H2 heading where conflict was injected
    body_excerpt: str  # the `> ⚠️ CONFLICT: ...` marker line + context


@dataclass
class NeedsReviewItem:
    page_relpath: str
    title: str
    confidence: str  # "low" | "medium" | "high"
    sources: list[str]
    pinned_fields: list[str]


@dataclass
class AmbiguityItem:
    page_relpath: str
    description: str  # text of `> ⚠️ AMBIGUOUS: <description>`
    body_excerpt: str


@dataclass
class UnclearTopicItem:
    page_relpath: str
    topic: str  # text of `> ⚠️ UNCLEAR: <topic>`
    body_excerpt: str


@dataclass
class ReviewChecklist:
    conflicts: list[ConflictItem] = field(default_factory=list)
    needs_review_pages: list[NeedsReviewItem] = field(default_factory=list)
    ambiguities: list[AmbiguityItem] = field(default_factory=list)
    unclear_topics: list[UnclearTopicItem] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.total_items() == 0

    def total_items(self) -> int:
        return (
            len(self.conflicts)
            + len(self.needs_review_pages)
            + len(self.ambiguities)
            + len(self.unclear_topics)
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CONFLICT_LINE_RE = re.compile(r"^>\s*⚠️\s*CONFLICT[::]\s*(.*)$", re.MULTILINE)
_AMBIGUOUS_LINE_RE = re.compile(r"^>\s*⚠️\s*AMBIGUOUS[::]\s*(.*)$", re.MULTILINE)
_UNCLEAR_LINE_RE = re.compile(r"^>\s*⚠️\s*UNCLEAR[::]\s*(.*)$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _section_for_position(body: str, pos: int) -> str:
    """Return the H2 section name that contains `body[pos]`, or '' if none."""
    section = ""
    for m in _H2_RE.finditer(body):
        if m.start() > pos:
            break
        section = m.group(1).strip()
    return section


def _excerpt_around(body: str, pos: int, span: int = 240) -> str:
    start = max(0, pos - span // 2)
    end = min(len(body), pos + span // 2)
    return body[start:end].strip()


def _read_page(path: Path) -> tuple[dict[str, Any], str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm = yaml.safe_load(parts[1]) or {}
    return (fm if isinstance(fm, dict) else {}), parts[2]


# ---------------------------------------------------------------------------
# scan_conflicts
# ---------------------------------------------------------------------------


def scan_conflicts(vault_dir: Path | str) -> list[ConflictItem]:
    """Scan all wiki pages for `> ⚠️ CONFLICT: ...` markers."""
    vault_dir = Path(vault_dir)
    out: list[ConflictItem] = []
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return out
    for path in sorted(wiki.rglob("*.md")):
        page = _read_page(path)
        if page is None:
            continue
        _fm, body = page
        for m in _CONFLICT_LINE_RE.finditer(body):
            section = _section_for_position(body, m.start())
            out.append(
                ConflictItem(
                    page_relpath=str(path.relative_to(vault_dir)).replace("\\", "/"),
                    section_name=section,
                    body_excerpt=_excerpt_around(body, m.start()),
                )
            )
    return out


# ---------------------------------------------------------------------------
# scan_needs_review
# ---------------------------------------------------------------------------


def scan_needs_review(vault_dir: Path | str) -> list[NeedsReviewItem]:
    """Scan all wiki pages for frontmatter `needs_review: true`."""
    vault_dir = Path(vault_dir)
    out: list[NeedsReviewItem] = []
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return out
    for path in sorted(wiki.rglob("*.md")):
        page = _read_page(path)
        if page is None:
            continue
        fm, _body = page
        if not fm.get("needs_review"):
            continue
        out.append(
            NeedsReviewItem(
                page_relpath=str(path.relative_to(vault_dir)).replace("\\", "/"),
                title=fm.get("title") or path.stem,
                confidence=fm.get("confidence", "low"),
                sources=list(fm.get("sources", []) or []),
                pinned_fields=list(fm.get("pinned_fields", []) or []),
            )
        )
    return out


# ---------------------------------------------------------------------------
# scan_ambiguities + scan_unclear_topics
# ---------------------------------------------------------------------------


def scan_ambiguities(vault_dir: Path | str) -> list[AmbiguityItem]:
    """Scan all wiki pages for `> ⚠️ AMBIGUOUS: ...` markers."""
    vault_dir = Path(vault_dir)
    out: list[AmbiguityItem] = []
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return out
    for path in sorted(wiki.rglob("*.md")):
        page = _read_page(path)
        if page is None:
            continue
        _fm, body = page
        for m in _AMBIGUOUS_LINE_RE.finditer(body):
            out.append(
                AmbiguityItem(
                    page_relpath=str(path.relative_to(vault_dir)).replace("\\", "/"),
                    description=m.group(1).strip(),
                    body_excerpt=_excerpt_around(body, m.start()),
                )
            )
    return out


def scan_unclear_topics(vault_dir: Path | str) -> list[UnclearTopicItem]:
    """Scan all wiki pages for `> ⚠️ UNCLEAR: ...` markers."""
    vault_dir = Path(vault_dir)
    out: list[UnclearTopicItem] = []
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return out
    for path in sorted(wiki.rglob("*.md")):
        page = _read_page(path)
        if page is None:
            continue
        _fm, body = page
        for m in _UNCLEAR_LINE_RE.finditer(body):
            out.append(
                UnclearTopicItem(
                    page_relpath=str(path.relative_to(vault_dir)).replace("\\", "/"),
                    topic=m.group(1).strip(),
                    body_excerpt=_excerpt_around(body, m.start()),
                )
            )
    return out


# ---------------------------------------------------------------------------
# build_checklist
# ---------------------------------------------------------------------------


def build_checklist(vault_dir: Path | str) -> ReviewChecklist:
    """Top-level scanner: returns a ReviewChecklist combining all 4 buckets."""
    vault_dir = Path(vault_dir)
    return ReviewChecklist(
        conflicts=scan_conflicts(vault_dir),
        needs_review_pages=scan_needs_review(vault_dir),
        ambiguities=scan_ambiguities(vault_dir),
        unclear_topics=scan_unclear_topics(vault_dir),
    )


# ---------------------------------------------------------------------------
# emit_prompt — Phase B/C orchestration message for Claude main conversation
# ---------------------------------------------------------------------------


_PROMPT_TEMPLATE = """\
# CloneMate Review — Phase B/C orchestration

You are Claude main conversation, invoked by `clonemate review {slug}` (or
auto-continued from `clonemate ingest-finish`). Vault path:

  {vault_dir}

Identity:
- target_open_id: {target_open_id}
- display_name:   {display_name}

## What this is

This is **Phase B/C** of the silent-ingest closed loop (spec §3 decision 9):
M3 ingest already finished writing wiki/. Phase B has scanned the wiki and
produced the checklist below. Phase C is **you talking to the user** to apply
each decision. The user **may exit at any time** — incomplete items remain
`[需复核]` and don't block.

## Red lines

- 不要假装用户没说过的事 — 每个写入必须基于用户当前回答
- 事实正确 > 风格化 (spec §8.5)
- voice 红线在代码层 (merge_note);此 review 不动 voice 内容,只可能 pin/unpin
- 任何修改通过 `merge_note.write` / `pin` / `unpin` / `resolve_conflict`,**绝不**直接 file.write_text wiki

## Phase B Checklist ({total} items)

{conflict_section}
{needs_review_section}
{ambiguity_section}
{unclear_section}

## Phase C dialogue script

Read `references/prompt-review.md` and `references/prompt-conflict.md` for the
4-option per-item dialogue (`[A] 接受 [B] 改 [C] 跳过 [D] 我补充`) and the
conflict-resolution sub-flow.

After processing all items (or user says "够了"):
1. Call `python -m clonemate review-finish --root {root} --slug {slug} --resolved <K> --skipped <N>`
2. Stop. Don't proceed to query (M5) or lint (M6).
"""

_NO_ITEMS_TEMPLATE = """\
# CloneMate Review — no items to review

Vault {vault_dir} has no conflicts / needs_review pages / ambiguities / unclear
topics. The wiki is in a clean state. Nothing for Phase B/C to do.

Run `python -m clonemate review-finish --root {root} --slug {slug} --resolved 0 --skipped 0`
to log this empty review pass.
"""


def emit_prompt(vault_dir: Path | str) -> str:
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    cl = build_checklist(vault_dir)

    if cl.is_empty():
        return _NO_ITEMS_TEMPLATE.format(
            vault_dir=vault_dir,
            root=vault_dir.parent,
            slug=cy["slug"],
        )

    return _PROMPT_TEMPLATE.format(
        vault_dir=vault_dir,
        root=vault_dir.parent,
        slug=cy["slug"],
        target_open_id=cy["identity"]["open_id"],
        display_name=cy["display_name"],
        total=cl.total_items(),
        conflict_section=_render_conflicts(cl.conflicts),
        needs_review_section=_render_needs_review(cl.needs_review_pages),
        ambiguity_section=_render_ambiguities(cl.ambiguities),
        unclear_section=_render_unclear(cl.unclear_topics),
    )


def _render_conflicts(items: list[ConflictItem]) -> str:
    if not items:
        return "### 🚨 Conflicts (0)\n\n(none)"
    lines = [f"### 🚨 Conflicts ({len(items)})", ""]
    for i, c in enumerate(items, 1):
        lines.append(f"{i}. **{c.page_relpath}** — section `{c.section_name}`")
        lines.append(f"   excerpt: `{c.body_excerpt[:120]}…`")
    return "\n".join(lines)


def _render_needs_review(items: list[NeedsReviewItem]) -> str:
    if not items:
        return "### 📋 Needs review / `needs_review` (0)\n\n(none)"
    lines = [f"### 📋 Needs review / `needs_review` ({len(items)})", ""]
    for i, p in enumerate(items, 1):
        lines.append(
            f"{i}. **{p.page_relpath}** — `{p.title}` "
            f"(confidence={p.confidence}, sources={p.sources})"
        )
    return "\n".join(lines)


def _render_ambiguities(items: list[AmbiguityItem]) -> str:
    if not items:
        return "### ❓ Ambiguities (0)\n\n(none)"
    lines = [f"### ❓ Ambiguities ({len(items)})", ""]
    for i, a in enumerate(items, 1):
        lines.append(f"{i}. **{a.page_relpath}** — {a.description[:120]}")
    return "\n".join(lines)


def _render_unclear(items: list[UnclearTopicItem]) -> str:
    if not items:
        return "### 🌫 Unclear topics (0)\n\n(none)"
    lines = [f"### 🌫 Unclear topics ({len(items)})", ""]
    for i, u in enumerate(items, 1):
        lines.append(f"{i}. **{u.page_relpath}** — {u.topic[:120]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# finish — rebuild index + log + auto-commit (Codex round 3 Finding 9)
# ---------------------------------------------------------------------------


def finish(vault_dir: Path | str, *, resolved: int, skipped: int) -> None:
    """Called by Claude main conversation after Phase C dialogue ends.

    Codex round 3 Finding 9: auto-commit the vault git history so subsequent
    conflict-resolution flows can recover prior section bodies via `git show`.
    """
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    log = vault_dir / "log.md"
    # lazy import to break cycles
    from clonemate import git_ops, index_upsert, log_append
    index_upsert.rebuild(vault_dir, display_name=cy["display_name"], log_path=log)
    log_append.append(
        log, op="review", subject=cy["slug"],
        metric=f"+{resolved} resolved / +{skipped} skipped",
    )
    # Auto-commit the post-review state (spec §3 decision 15 / Codex
    # Findings 9+11). Real failures (missing git config, lock, permission)
    # MUST surface; only skip when there is nothing to commit.
    git_ops._auto_commit_vault(
        vault_dir,
        message=f"review: +{resolved} resolved / +{skipped} skipped",
    )
