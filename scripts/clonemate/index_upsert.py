"""index_upsert — read wiki/, regenerate index.md.

Pure read-only over wiki/; writes only to index.md. Never edits wiki pages.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_CONFLICT_RE = re.compile(r"^>\s*⚠️\s*CONFLICT\b", re.MULTILINE)


@dataclass
class PageSummary:
    page_type: str
    title: str
    relative_path: str
    sources: list[str]
    confidence: str
    needs_review: bool
    has_conflict: bool


@dataclass
class WikiSummary:
    pages: list[PageSummary] = field(default_factory=list)
    needs_review_count: int = 0
    conflict_count: int = 0


def _parse_page(path: Path, vault: Path) -> PageSummary | None:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm: dict[str, Any] = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    return PageSummary(
        page_type=fm.get("page_type", "unknown"),
        title=fm.get("title") or path.stem,
        relative_path=str(path.relative_to(vault)).replace("\\", "/"),
        sources=list(fm.get("sources", []) or []),
        confidence=fm.get("confidence", "low"),
        needs_review=bool(fm.get("needs_review", False)),
        has_conflict=bool(_CONFLICT_RE.search(body)),
    )


def scan_wiki(vault_dir: Path) -> WikiSummary:
    """Scan vault/wiki/ recursively and produce a structural summary."""
    vault_dir = Path(vault_dir)
    wiki = vault_dir / "wiki"
    summary = WikiSummary()
    if not wiki.is_dir():
        return summary
    for path in sorted(wiki.rglob("*.md")):
        page = _parse_page(path, vault_dir)
        if page is None:
            continue
        summary.pages.append(page)
        if page.needs_review:
            summary.needs_review_count += 1
        if page.has_conflict:
            summary.conflict_count += 1
    return summary


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def _count_sources(summary: WikiSummary) -> int:
    seen: set[str] = set()
    for p in summary.pages:
        seen.update(p.sources)
    return len(seen)


def rebuild(vault_dir: Path, *, display_name: str, log_path: Path | None = None) -> None:
    """Regenerate index.md from current wiki/ contents."""
    vault_dir = Path(vault_dir)
    summary = scan_wiki(vault_dir)
    by_type: dict[str, list[PageSummary]] = {}
    for p in summary.pages:
        by_type.setdefault(p.page_type, []).append(p)

    lines = [
        f"# {display_name} · CloneMate Index",
        "",
        f"> 最后更新:{_now_iso()} | 来源数:{_count_sources(summary)} | "
        f"wiki 页:{len(summary.pages)} | 待复核:{summary.needs_review_count} | "
        f"冲突:{summary.conflict_count}",
        "",
        "## 🚨 待裁决",
        "",
    ]
    triage_lines = []
    for p in summary.pages:
        if p.has_conflict:
            triage_lines.append(
                f"- [conflict] [{p.title}]({p.relative_path}) "
                f"(sources: {', '.join(p.sources) or '—'})"
            )
        if p.needs_review and not p.has_conflict:
            triage_lines.append(f"- [需复核] [{p.title}]({p.relative_path})")
    lines.extend(triage_lines or ["(空)"])
    lines.append("")

    for header, type_key in [
        ("👤 Persona", "persona"),
        ("🎙 Voice", "voice"),
        ("🏷️ Entities", "entity"),
        ("💡 Concepts", "concept"),
        ("🔗 Syntheses", "synthesis"),
        ("📥 Sources", "source_summary"),
    ]:
        lines.append(f"## {header}")
        lines.append("")
        bucket = sorted(by_type.get(type_key, []), key=lambda p: p.title)
        if not bucket:
            lines.append("(空)")
        else:
            for p in bucket:
                lines.append(f"- [{p.title}]({p.relative_path}) — confidence={p.confidence}")
        lines.append("")

    (vault_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")

    if log_path is not None:
        from clonemate import log_append  # noqa: PLC0415

        log_append.append(
            log_path,
            op="index_rebuild",
            subject=display_name,
            metric=(
                f"{len(summary.pages)} pages / "
                f"{summary.needs_review_count} needs-review / "
                f"{summary.conflict_count} conflicts"
            ),
        )


def update_page(vault_dir: Path, *, page_path: Path, display_name: str) -> None:
    """Incrementally update index.md to reflect changes to one wiki page.

    M3 simplification: re-render the whole index. Future optimisation could
    do a true diff, but the rebuild is fast (linear in #pages) and the
    semantics are equivalent.
    """
    rebuild(vault_dir, display_name=display_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clonemate.index_upsert")
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    vault = Path(args.vault_dir)
    if not (vault / "wiki").is_dir():
        print(f"no wiki/ at {vault}", file=sys.stderr)
        return 2
    rebuild(vault, display_name=args.display_name)
    print(f"OK: rebuilt {vault / 'index.md'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
