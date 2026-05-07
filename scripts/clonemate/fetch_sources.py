# scripts/clonemate/fetch_sources.py
"""fetch_sources — orchestrator. Reads _clone.yaml, runs each enabled adapter,
writes raws via RawWriter, advances cursors only on full success per source.

KEY INVARIANT (spec §3 decision 17 / §6.6): a source's cursor is advanced ONLY
when fetch + raw_writer.write_all + _clone.yaml save all succeed. On any error,
cursor stays put — the next sync re-fetches from the same start.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clonemate import parse_since
from clonemate.adapters._base import FetchContext
from clonemate.raw_writer import RawWriter


@dataclass
class SourceReport:
    name: str
    written: int = 0
    skipped: int = 0
    failed: bool = False
    error: str | None = None
    skipped_reason: str | None = None
    # When an adapter completes "partially" (e.g. some docs fetched, others failed)
    # the cursor stays put (status='partial') so the next sync retries.  This
    # field surfaces the per-item errors to the caller without flagging the
    # whole source as failed.  spec §3 decision 17 / Codex Finding 4.
    partial_errors: dict[str, str] | None = None


@dataclass
class FetchReport:
    per_source: dict[str, SourceReport] = field(default_factory=dict)


def _built_in_adapters() -> dict[str, Any]:
    """Lazy import to keep module load fast and break circular deps."""
    from clonemate.adapters.calendar_titles import CalendarTitlesAdapter
    from clonemate.adapters.contact import ContactAdapter
    from clonemate.adapters.doc_comments import DocCommentsAdapter
    from clonemate.adapters.docs_owned import DocsOwnedAdapter
    from clonemate.adapters.im_1v1 import Im1v1Adapter
    from clonemate.adapters.im_group import ImGroupAdapter
    from clonemate.adapters.meego import MeegoStub
    from clonemate.adapters.minutes import MinutesAdapter
    return {
        "contact": ContactAdapter(),
        "im_1v1": Im1v1Adapter(),
        "im_group": ImGroupAdapter(),
        "minutes": MinutesAdapter(),
        "docs_owned": DocsOwnedAdapter(),
        "doc_comments": DocCommentsAdapter(),
        "calendar_titles": CalendarTitlesAdapter(),
        "meego": MeegoStub(),
    }


def run(*, vault_dir: Path, my_open_id: str, since_str: str | None) -> FetchReport:
    cy_path = vault_dir / "_clone.yaml"
    cy = yaml.safe_load(cy_path.read_text(encoding="utf-8"))

    since = parse_since.parse_since(since_str)
    writer = RawWriter(vault_dir)
    adapters = _built_in_adapters()
    report = FetchReport()

    # Collect docs_owned (token, doc_type) tuples to feed into doc_comments.
    docs_owned_entries: list[dict[str, str]] = []

    for name, adapter in adapters.items():
        if not cy.get("sources_enabled", {}).get(name, False):
            continue
        cursor = dict(cy.get("cursors", {}).get(name, {}))
        if name == "doc_comments":
            cursor["doc_entries_to_scan"] = docs_owned_entries

        ctx = FetchContext(
            open_id=cy["identity"]["open_id"],
            my_open_id=my_open_id,
            since=since,
            profile=cy.get("profile", "claude-code"),
            quota=cy.get("quota", {"per_source_max_messages": 1000}),
            cursor=cursor,
        )
        srep = SourceReport(name=name)
        try:
            result = adapter.fetch(ctx)
            if result.skipped_reason:
                srep.skipped_reason = result.skipped_reason
                report.per_source[name] = srep
                continue
            for cand in result.raws:
                wr = writer.write(cand)
                if wr.written:
                    srep.written += 1
                else:
                    srep.skipped += 1
                if name == "docs_owned":
                    tok = cand.frontmatter.get("doc_token")
                    if tok:
                        docs_owned_entries.append({
                            "token": tok,
                            "doc_type": cand.frontmatter.get("doc_type", "docx"),
                        })
            # Always store the adapter's next_cursor — it embeds 'partial' state
            # (with last_modified_at preserved) when retries are pending.
            cy.setdefault("cursors", {})[name] = result.next_cursor
            # Surface partial state to the report + write per-item errors to error.log.
            if result.next_cursor.get("status") == "partial":
                srep.partial_errors = dict(result.next_cursor.get("per_doc_errors", {}))
                if srep.partial_errors:
                    (vault_dir / "raw" / name).mkdir(parents=True, exist_ok=True)
                    with (vault_dir / "raw" / name / ".error.log").open("a", encoding="utf-8") as fh:
                        ts = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
                        for tok, msg in srep.partial_errors.items():
                            fh.write(f"[{ts}] partial: {tok}: {msg}\n")
        except Exception as exc:  # noqa: BLE001
            srep.failed = True
            srep.error = str(exc)
            (vault_dir / "raw" / name).mkdir(parents=True, exist_ok=True)
            (vault_dir / "raw" / name / ".error.log").write_text(
                f"[{_dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec='seconds')}] {exc}\n",
                encoding="utf-8",
            )
            # cursor NOT advanced
        report.per_source[name] = srep

    cy["last_sync_run_at"] = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    cy_path.write_text(yaml.safe_dump(cy, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return report
