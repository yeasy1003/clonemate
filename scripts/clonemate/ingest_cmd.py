"""ingest_cmd — orchestrator for `clonemate ingest <slug>`.

This module DOES NOT call any LLM. It:
  - lists raw files grouped by source_type (input for subagent dispatch)
  - emits the orchestration prompt for Claude main conversation
  - after Claude+subagents have written wiki, calls index_upsert + log_append

The actual LLM work (reading raws, deciding what to write) happens in Claude
main conversation per `references/prompt-ingest.md` and `references/workflow-ingest.md`.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def list_raw(vault_dir: Path | str) -> dict[str, list[Path]]:
    """Return {source_type: [raw_file_paths]} for ingest. Skips hidden files."""
    raw = Path(vault_dir) / "raw"
    grouped: dict[str, list[Path]] = {}
    if not raw.is_dir():
        return grouped
    for entry in sorted(raw.iterdir()):
        if not entry.is_dir():
            continue
        # entry is a source_type directory; collect *.md inside it (recursive).
        source_type = entry.name
        files = sorted(p for p in entry.rglob("*.md") if not p.name.startswith("."))
        if files:
            grouped[source_type] = files
    return grouped


_PROMPT_TEMPLATE = """\
# CloneMate Ingest — main-conversation orchestration prompt

You are Claude main conversation. The user just ran `clonemate ingest` for vault at:

  {vault_dir}

Below is the per-source raw inventory, identity, and a checklist. Follow
`references/prompt-ingest.md` and `references/workflow-ingest.md` verbatim.

## Identity

target_open_id: {target_open_id}
display_name:   {display_name}

## Raw inventory

{raw_inventory}

## Red-line reminders

- **作者归属** (spec §3 决策 18): voice / persona / few-shot 仅取 author_open_id == target_open_id
- voice 来源限制: 仅 im_1v1 / im_group(ta 自己) / minutes(ta 段) / comments(author == ta);**禁** docs 正文
- 事实正确 > 风格化: 任何 wiki 事实必须可追溯到 src_id
- 占位符护栏: vault 内可用真实数据,但不要泄漏到 plan / spec / commit message

## Steps

1. Read `references/prompt-ingest.md` — full ingest contract
2. Read `references/workflow-ingest.md` — subagent dispatch matrix
3. Dispatch 4 subagents (sub-A / sub-B / sub-C / sub-D per workflow doc) IN PARALLEL
4. Wait for all subagents to report DONE (each writes wiki via `merge_note.write`)
5. Run: `python -m clonemate.index_upsert --vault-dir {vault_dir} --display-name "{display_name}"`
6. Append log entry via `clonemate.log_append.append(
   <vault>/log.md, op='ingest', subject='initial-ingest', metric='+N raw / +M wiki')`
7. Stop. Do NOT proceed to Phase B / Phase C — those are M4.
"""


def emit_prompt(vault_dir: Path | str) -> str:
    """Build the orchestration message for Claude main conversation."""
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    grouped = list_raw(vault_dir)
    inv_lines = []
    for stype, files in grouped.items():
        inv_lines.append(f"- {stype}: {len(files)} files")
        for f in files:
            inv_lines.append(f"  - {f.relative_to(vault_dir)}")
    return _PROMPT_TEMPLATE.format(
        vault_dir=vault_dir,
        target_open_id=cy["identity"]["open_id"],
        display_name=cy["display_name"],
        raw_inventory="\n".join(inv_lines) or "(empty)",
    )


def finish(vault_dir: Path | str, *, raw_count: int, wiki_count: int) -> None:
    """Called by Claude main conversation after all subagents finish writing wiki.

    Codex round 3 Finding 9: auto-commit so subsequent review can recover
    prior section bodies via `git show`.
    """
    from clonemate import git_ops, index_upsert, log_append

    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    log = vault_dir / "log.md"
    index_upsert.rebuild(vault_dir, display_name=cy["display_name"], log_path=log)
    log_append.append(
        log,
        op="ingest",
        subject="initial-ingest",
        metric=f"+{raw_count} raw / +{wiki_count} wiki",
    )
    git_ops._auto_commit_vault(
        vault_dir,
        message=f"ingest: +{raw_count} raw / +{wiki_count} wiki",
    )
