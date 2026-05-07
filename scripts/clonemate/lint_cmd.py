"""lint_cmd — Phase lint orchestrator.

Phase lint produces a health report combining:
  - 4 static scanners (Python): orphan / missing-sources / dead-refs / 90d-stale
  - 1 dynamic scanner (Claude main conversation, driven by emit_prompt):
    cross-page contradictions / missing concept pages / source gaps

This module is LLM-free per spec §4.2. The actual report is for human reading;
no automatic remediation. Claude may surface follow-up actions; the user
decides.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class OrphanPage:
    page_relpath: str  # relative to vault_dir, forward-slash


@dataclass
class MissingSourcesPage:
    page_relpath: str


@dataclass
class DeadRef:
    page_relpath: str
    missing_src_id: str


@dataclass
class StalePage:
    page_relpath: str
    days_since: int


@dataclass
class LintReport:
    orphan_pages: list[OrphanPage] = field(default_factory=list)
    missing_sources_pages: list[MissingSourcesPage] = field(default_factory=list)
    dead_refs: list[DeadRef] = field(default_factory=list)
    stale_pages: list[StalePage] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.total_findings() == 0

    def total_findings(self) -> int:
        return (
            len(self.orphan_pages)
            + len(self.missing_sources_pages)
            + len(self.dead_refs)
            + len(self.stale_pages)
        )


def _read_page(path: Path) -> tuple[dict, str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm = yaml.safe_load(parts[1]) or {}
    return (fm if isinstance(fm, dict) else {}), parts[2]


_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _index_link_targets(index_text: str) -> set[str]:
    """Codex round 1 Finding 9: parse `[text](path)` markdown links from
    index.md instead of substring-matching page names. Defends against
    short page names that would otherwise false-negative orphan detection."""
    return {m.group(1).strip() for m in _MD_LINK_RE.finditer(index_text)}


def scan_orphan_pages(vault_dir: Path | str) -> list[OrphanPage]:
    """Pages under wiki/ that no markdown link in index.md targets.

    Excludes voice.md and persona.md (always-present root pages).
    Returns empty list if index.md is missing.

    Codex round 1 Finding 9: uses link-target parsing, not substring match.
    """
    vault_dir = Path(vault_dir)
    index_path = vault_dir / "index.md"
    if not index_path.is_file():
        return []
    targets = _index_link_targets(index_path.read_text(encoding="utf-8"))
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return []
    out: list[OrphanPage] = []
    for path in sorted(wiki.rglob("*.md")):
        relpath = str(path.relative_to(vault_dir)).replace("\\", "/")
        if relpath in {"wiki/voice.md", "wiki/persona.md"}:
            continue
        if relpath in targets:
            continue
        out.append(OrphanPage(page_relpath=relpath))
    return out


def scan_missing_sources_pages(vault_dir: Path | str) -> list[MissingSourcesPage]:
    """Wiki pages whose frontmatter has empty or missing `sources` list.

    Voice page is exempt (template/initial state may have no sources).
    """
    vault_dir = Path(vault_dir)
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return []
    out: list[MissingSourcesPage] = []
    for path in sorted(wiki.rglob("*.md")):
        relpath = str(path.relative_to(vault_dir)).replace("\\", "/")
        if relpath == "wiki/voice.md":
            continue
        page = _read_page(path)
        if page is None:
            continue
        fm, _body = page
        sources = fm.get("sources")
        if not sources:  # None or empty list
            out.append(MissingSourcesPage(page_relpath=relpath))
    return out


def _all_existing_src_ids(raw_dir: Path) -> set[str]:
    """Walk raw/ and return the set of src_ids that physically exist (file basename)."""
    if not raw_dir.is_dir():
        return set()
    out: set[str] = set()
    for path in raw_dir.rglob("*.md"):
        out.add(path.stem)
    return out


def scan_dead_refs(vault_dir: Path | str) -> list[DeadRef]:
    """Wiki pages whose frontmatter sources list a src_id whose
    raw/<src_type>/<src_id>.md is missing."""
    vault_dir = Path(vault_dir)
    raw_dir = vault_dir / "raw"
    alive = _all_existing_src_ids(raw_dir)
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return []
    out: list[DeadRef] = []
    for path in sorted(wiki.rglob("*.md")):
        page = _read_page(path)
        if page is None:
            continue
        fm, _body = page
        relpath = str(path.relative_to(vault_dir)).replace("\\", "/")
        for sid in (fm.get("sources") or []):
            if sid not in alive:
                out.append(DeadRef(page_relpath=relpath, missing_src_id=sid))
    return out


def scan_stale_pages(
    vault_dir: Path | str,
    *,
    threshold_days: int = 90,
    today: _dt.date | None = None,
) -> list[StalePage]:
    """Wiki pages whose frontmatter `last_modified` is more than
    threshold_days before `today` (defaults to UTC today).

    Pages without `last_modified` are skipped — they should surface under
    `scan_missing_sources_pages` or other sanity checks instead.
    """
    vault_dir = Path(vault_dir)
    if today is None:
        today = _dt.date.today()
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return []
    out: list[StalePage] = []
    for path in sorted(wiki.rglob("*.md")):
        page = _read_page(path)
        if page is None:
            continue
        fm, _body = page
        ts = fm.get("last_modified")
        if not ts:
            continue
        try:
            modified = _dt.datetime.fromisoformat(str(ts)).date()
        except ValueError:
            continue
        days = (today - modified).days
        if days > threshold_days:
            relpath = str(path.relative_to(vault_dir)).replace("\\", "/")
            out.append(StalePage(page_relpath=relpath, days_since=days))
    return out


def build_report(vault_dir: Path | str) -> LintReport:
    """Top-level scanner: returns LintReport combining all 4 buckets."""
    vault_dir = Path(vault_dir)
    return LintReport(
        orphan_pages=scan_orphan_pages(vault_dir),
        missing_sources_pages=scan_missing_sources_pages(vault_dir),
        dead_refs=scan_dead_refs(vault_dir),
        stale_pages=scan_stale_pages(vault_dir),
    )


_PROMPT_TEMPLATE = """\
# CloneMate Lint — Phase lint orchestration

You are Claude main conversation, invoked by `clonemate lint {slug}`.
Vault path:

  {vault_dir}

Identity:
- target_open_id: {target_open_id}
- display_name:   {display_name}

## What this is

Phase lint is a health-check (spec §6.4). Static scanners (Python, already
run) found the issues below. Your job is the **dynamic** pass: cross-page
contradictions, missing concept pages, source gaps that the static scanners
can't see. Then surface findings to the user with a brief report — **do
NOT** auto-rewrite anything. Lint is read-only; remediation is via
`clonemate review` or `clonemate forget`.

## Static findings ({total} items)

{orphan_section}
{missing_sources_section}
{dead_ref_section}
{stale_section}

## Dynamic scan rubric (your job)

Read `references/prompt-lint.md` for the per-bucket dialogue and the
following quality dimensions:

1. **跨页矛盾** — same fact stated differently across pages.
2. **缺失概念页** — recurring entity/concept mentioned ≥3 times but no
   dedicated wiki page.
3. **缺失交叉引用** — concept page X mentions entity Y but Y page doesn't
   mention X.
4. **source 缺口** — scope assumed by frontmatter but no cited src in body.

For each bucket, list findings (terse). The user reviews; **do not** apply
changes from the lint flow.

## Finish

After surfacing findings (or if static-only and you have nothing dynamic to add):

  python -m clonemate lint-finish --root {root} --slug {slug}

Stop. Do not transition to forget (M6) or sync (M7).
"""

_NO_ITEMS_TEMPLATE = """\
# CloneMate Lint — clean

Vault {vault_dir} has no static lint findings (no orphan / missing-sources /
dead-refs / 90d-stale pages). Your dynamic-scan pass may still surface
issues, but the static check is clean.

If you find nothing in dynamic scan either, run:

  python -m clonemate lint-finish --root {root} --slug {slug}
"""


def emit_prompt(vault_dir: Path | str) -> str:
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    rpt = build_report(vault_dir)

    if rpt.is_empty():
        return _NO_ITEMS_TEMPLATE.format(
            vault_dir=vault_dir, root=vault_dir.parent, slug=cy["slug"],
        )

    return _PROMPT_TEMPLATE.format(
        vault_dir=vault_dir,
        root=vault_dir.parent,
        slug=cy["slug"],
        target_open_id=cy["identity"]["open_id"],
        display_name=cy["display_name"],
        total=rpt.total_findings(),
        orphan_section=_render_orphans(rpt.orphan_pages),
        missing_sources_section=_render_missing_sources(rpt.missing_sources_pages),
        dead_ref_section=_render_dead_refs(rpt.dead_refs),
        stale_section=_render_stale(rpt.stale_pages),
    )


def _render_orphans(items: list[OrphanPage]) -> str:
    if not items:
        return "### 🍂 Orphan pages (0)\n\n(none)"
    lines = [f"### 🍂 Orphan pages ({len(items)})", ""]
    lines.extend(f"- `{o.page_relpath}`" for o in items)
    return "\n".join(lines)


def _render_missing_sources(items: list[MissingSourcesPage]) -> str:
    if not items:
        return "### 📭 Missing sources (0)\n\n(none)"
    lines = [f"### 📭 Missing sources ({len(items)})", ""]
    lines.extend(f"- `{p.page_relpath}`" for p in items)
    return "\n".join(lines)


def _render_dead_refs(items: list[DeadRef]) -> str:
    if not items:
        return "### 💀 Dead refs (0)\n\n(none)"
    lines = [f"### 💀 Dead refs ({len(items)})", ""]
    lines.extend(f"- `{d.page_relpath}` → missing `{d.missing_src_id}`" for d in items)
    return "\n".join(lines)


def _render_stale(items: list[StalePage]) -> str:
    if not items:
        return "### 🕰 Stale pages (0)\n\n(none)"
    lines = [f"### 🕰 Stale pages ({len(items)})", ""]
    lines.extend(f"- `{s.page_relpath}` ({s.days_since}d)" for s in items)
    return "\n".join(lines)


def finish(vault_dir: Path | str, *, findings: int) -> None:
    """Called by Claude main conversation after the dynamic scan + report.

    `findings` is the total count surfaced (static + dynamic). The actual
    list is in the conversation; we only persist a count + timestamp.
    """
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    log = vault_dir / "log.md"
    from clonemate import git_ops, log_append
    log_append.append(
        log, op="lint", subject=cy["slug"],
        metric=f"{findings} findings" if findings else "clean (0 findings)",
    )
    git_ops._auto_commit_vault(vault_dir, message=f"lint: {findings} findings")
