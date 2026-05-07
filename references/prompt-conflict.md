# Conflict Resolution Sub-flow

> **Audience:** Claude main conversation processing a `ConflictItem` from
> Phase B checklist.

## Context

A conflict is a `> ⚠️ CONFLICT: section <name> rewritten by ingest; older
version available in git history.` marker injected by `merge_note._merge_body`
when a re-ingest tried to overwrite an existing same-named H2 section.

The user needs to choose between v1 (old, in git history) and v2 (current
content) — or write a v3.

## Steps

1. **Show user the section**:
   - The current section content (v2 — already in the page)
   - The original v1 from `git show HEAD~<n>:<page_relpath>` if recoverable
     (use `git_ops.run` to fetch it). If not in git (raw not committed), tell
     the user "v1 已不可恢复 — 请直接给最终版本".

2. **Ask** the same 4 options as the regular review:
   > [A] 保留 v2 (current);标 confidence high
   > [B] 用 v1 (older);你拍板
   > [C] 跳过 — 留冲突标记
   > [D] 给我 v3 — 你给最终内容

3. **Apply**:
   - [A]: `merge_note.resolve_conflict(..., accepted_body=<v2 content>, decided_by_user=True)` — drops marker, keeps v2.
   - [B]: `merge_note.resolve_conflict(..., accepted_body=<v1 content>)` — drops marker, replaces with v1.
   - [C]: Do nothing. Marker remains. Move on.
   - [D]: Ask user, then `merge_note.resolve_conflict(..., accepted_body=<v3 from user>)`.

## Sources

When applying, the existing frontmatter sources are preserved (sources union from M3 logic). If user-given v3 references a new src_id not in existing sources, the user can pass it; merge_note will union it.

## Don't

- Don't auto-resolve based on confidence alone — Phase C is user-driven.
- Don't drop a marker without applying a chosen body — that loses provenance.
