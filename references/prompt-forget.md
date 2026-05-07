# Phase forget — Level 2 Dirty-Page Rewrite Rubric

> **Audience:** Claude main conversation, invoked by `clonemate forget
> <slug> --source <src-id>`.

## What you have

The orchestration message lists the dirty pages (frontmatter mentioned
the dropped src-XXX). Each page's `pinned_fields` and `confidence` were
already audited:

- sole-source pages: pins cleared, `needs_review: true`
- shared-source pages: confidence demoted (high→medium→low), `needs_review: true`

Your job: rewrite each dirty page so its content no longer relies on the
dropped src-XXX.

## Per-page workflow

For each dirty page in the checklist:

1. **Read the page**.
2. **Read remaining sources** (frontmatter `sources:` minus the dropped
   one). If a page is now sourceless, the rewrite is mostly "delete
   content".
3. **For each H2 section**:
   - If the section's content was supported only by the dropped src →
     **delete the section** entirely. Don't keep `confidence: low +
     sources: []` stubs.
   - If shared-source → rewrite using only the remaining sources, soften
     low-confidence claims.
4. **If the entire page body is now empty (all sections deleted)** →
   write a minimal `# {{title}}\n\n## (page contents removed by forget)\n`
   placeholder. Future versions of M6 may add `merge_note.delete_page`
   for true page deletion.
5. **Call `merge_note.forget_rewrite(...)`** (NOT `merge_note.write`).
   The forget-specific entry point replaces `sources` (M5's regular `write`
   would UNION new sources with the existing list — leaving the forgotten
   source in frontmatter forever). It also clears the `forget_dirty`
   marker that `forget_level2_start` set on each dirty page.

   ```python
   from clonemate import merge_note
   merge_note.forget_rewrite(
       vault_dir=Path("<vault_dir>"),
       page_type="entity",  # or 'concept' / 'synthesis' (NOT 'voice' — raises)
       title="<page title>",
       sources=[<remaining sources, with forgotten src DROPPED>],
       confidence="<post-audit value>",
       needs_review=True,
       body="<rewritten body>",
   )
   ```

## Red lines

- voice / persona core 不动 — voice.md is read-only here. If persona
  pinned_fields were cleared in the audit, the page body still gets
  rewritten; pinned-fields metadata is updated in the next user-driven
  re-pin via `clonemate review` later.
- 引用前必须确认 `author_open_id == target.open_id`. Don't bring in
  third-party content while rewriting.
- 不要"补"内容来填空。If a section becomes empty, delete it.

## Finish

After rewriting all dirty pages:

  python -m clonemate forget-finish --root <root> --slug <slug> --source <src-id>

This runs `git filter-repo --replace-text` to scrub the src-id from history,
clears the `forget_dirty` markers (if any survived), rebuilds the index,
logs the op, and final-commits.

## Don't

- Don't run `forget-finish` until ALL dirty pages have been rewritten.
  filter-repo is destructive; you only want to invoke it once per source.
- Don't delete the page placeholder — at most leave a "(page contents
  removed by forget)" note so the user knows the page existed.
