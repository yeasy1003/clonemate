"""sync_cmd — incremental fetch with profile gating + source filters.

Spec §6.6: sync re-runs fetch_sources with the SAME cursors as the last run.
Per-source cursor isolation + failure isolation are inherited from M2's
fetch_sources.run. M7 sync adds:
  - profile_check.verify_profile (spec §8.7)
  - --source <name> filter (single source for debugging / CI)
  - --retry-failed filter (re-run only sources with cursors.<name>.status='failed')

This module is LLM-free (spec §4.2).
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import yaml

from clonemate import profile_check


@contextlib.contextmanager
def _temporarily_filter_sources_enabled(
    vault_dir: Path, *, keep_only: set[str],
) -> Iterator[None]:
    """Temporarily restrict `sources_enabled` to the given set; restore on exit.

    Used by `--source` and `--retry-failed` filters. The on-disk yaml is
    rewritten so fetch_sources picks up the filter; restored on exit so a
    subsequent fresh sync sees the original config.

    NOTE: re-reads the yaml AFTER fetch_sources.run (which mutates cursors /
    last_sync_run_at) and only swaps `sources_enabled` back — preserving any
    cursor advances written during the fetch.
    """
    cy_path = vault_dir / "_clone.yaml"
    cy = yaml.safe_load(cy_path.read_text(encoding="utf-8"))
    original = dict(cy.get("sources_enabled", {}))
    filtered = {name: (name in keep_only) for name in original}
    cy["sources_enabled"] = filtered
    cy_path.write_text(yaml.safe_dump(cy, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        yield
    finally:
        # Re-read AFTER fetch_sources mutated the file (cursor advances etc.),
        # then swap only `sources_enabled` back to the original. Don't wipe
        # cursor changes the fetch made.
        cy = yaml.safe_load(cy_path.read_text(encoding="utf-8"))
        cy["sources_enabled"] = original
        cy_path.write_text(yaml.safe_dump(cy, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _failed_sources(vault_dir: Path) -> set[str]:
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    cursors = cy.get("cursors") or {}
    out: set[str] = set()
    for name, c in cursors.items():
        if isinstance(c, dict) and c.get("status") == "failed":
            out.add(name)
    return out


def sync(
    vault_dir: Path | str,
    *,
    my_open_id: str,
    source_filter: str | None = None,
    retry_failed: bool = False,
    since: str | None = None,
):
    """Run an incremental sync. Returns the FetchReport."""
    from clonemate import fetch_sources
    vault_dir = Path(vault_dir)
    profile_check.verify_profile(vault_dir)

    if source_filter and retry_failed:
        raise ValueError("--source and --retry-failed are mutually exclusive")

    if source_filter:
        with _temporarily_filter_sources_enabled(vault_dir, keep_only={source_filter}):
            return fetch_sources.run(
                vault_dir=vault_dir, my_open_id=my_open_id, since_str=since,
            )

    if retry_failed:
        failed = _failed_sources(vault_dir)
        if not failed:
            # Nothing to retry — return empty report
            return fetch_sources.FetchReport()
        with _temporarily_filter_sources_enabled(vault_dir, keep_only=failed):
            return fetch_sources.run(
                vault_dir=vault_dir, my_open_id=my_open_id, since_str=since,
            )

    return fetch_sources.run(
        vault_dir=vault_dir, my_open_id=my_open_id, since_str=since,
    )


def finish(vault_dir: Path | str, *, report) -> None:
    """Append a per-source summary to log.md + auto-commit."""
    from clonemate import git_ops, log_append
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    log = vault_dir / "log.md"

    # Compose a one-line metric per source
    parts: list[str] = []
    for name, sr in sorted(report.per_source.items()):
        if sr.failed:
            parts.append(f"{name}: FAIL ({sr.error or 'unknown'})")
        elif sr.skipped_reason:
            parts.append(f"{name}: SKIP ({sr.skipped_reason})")
        else:
            parts.append(f"{name}: +{sr.written} (skipped={sr.skipped})")
    metric = " · ".join(parts) if parts else "no sources enabled"

    log_append.append(
        log, op="sync", subject=cy.get("slug", "?"), metric=metric,
    )
    git_ops._auto_commit_vault(vault_dir, message=f"sync: {metric[:60]}")
