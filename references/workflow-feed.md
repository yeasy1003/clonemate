# Feed Workflow

> **Audience:** Claude main conversation orchestrating Phase feed.

## Triggers

`clonemate feed <slug> --input <path|URL|->` or `--fact "..." --confidence X --title <title>`.

## Flow

1. profile_check.verify_profile (skipped for `--fact` since no fetch).
2. parser dispatch (text / lark_doc / lark_sheet / lark_minutes / pdf / docx / pptx / html).
3. raw_writer.write — content_hash dedup.
4. emit_prompt_for_ingest — Claude does incremental ingest per `prompt-feed.md`.
5. user runs `feed-finish` to log + commit.

## Don't

- Don't re-ingest the entire vault from feed — only the new raws.
- Don't write voice from feed.
- Don't try to feed `wiki/voice.md` directly — it's read-only outside ingest.
