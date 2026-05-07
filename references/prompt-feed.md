# Phase feed — Incremental Ingest Rubric

> **Audience:** Claude main conversation, invoked by `clonemate feed`.

The orchestration message lists the just-fed raw paths. Your job is
INCREMENTAL ingest — process ONLY the new raws, NOT the entire vault.

## Per-raw workflow

For each new `raw/<...>/<src_id>.md`:

1. Read it. Skip the frontmatter; extract the body.
2. Decide which wiki page(s) should reflect this material:
   - Persona / voice — only re-extract if `src_type` is im_1v1 / im_group /
     minutes / doc_comments AND `author == target`. **Voice red line: M5
     `merge_note.write` rejects voice writes from non-ingest authors.** Don't
     mutate voice from feed.
   - Entity / concept — most feed inputs go here. Use `merge_note.write` with
     section-aware merge (M3 logic).
   - Synthesis — only if the new material is a true cross-page comparison.

3. Always pass `author_role='ingest'` from feed (the user explicitly asked for
   ingest semantics). For URL-fetched lark docs, attribute `author_open_id`
   from doc metadata if available.

4. Honor M5 byte-equal idempotency — re-feeding the same content is a no-op.

## Don't

- Don't re-ingest the entire vault — only new raws.
- Don't write voice.md from feed.
- Don't fabricate facts the raw doesn't support.
- Don't skip frontmatter parsing — `author_open_id` is required for the §8.5
  red line.

## Finish

After processing all new raws:

  python -m clonemate feed-finish --root <root> --slug <slug> --written <N>

`<N>` = wiki pages updated (best estimate; doesn't have to be exact).

### `--written 0` is a valid outcome

If you decided the new raw didn't warrant any wiki update — e.g. content
was duplicate, irrelevant, or M5 byte-equal idempotency turned every
`merge_note.write` call into a no-op — pass `--written 0`. This is the
correct path: the log will record that the feed run was driven but no
wiki landed. Don't fabricate a fake update count to "look productive";
the log is the user's audit trail. (Codex round 3 Finding F.)
