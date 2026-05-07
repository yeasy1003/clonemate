# Query Workflow

> **Audience:** Claude main conversation orchestrating Phase ask.

## Triggers

Phase ask runs in two situations:

1. **User-invoked** (default): `clonemate ask <slug> "<question>"`. The CLI
   emits the Phase ask prompt; Claude reads it, runs 4a/4b/4c, replies to
   the user, optionally writes a synthesis, and calls `ask-finish`.

2. **Programmatic** (rare): another tool (e.g. M6 lint) shells out
   `python -m clonemate ask`. Same flow.

## Mode selection

| User intent | Flag | Behavior |
|---|---|---|
| Default — voice + facts + disclaimer | (none) | 4a + 4b + 4c |
| Quoteable factual summary | `--literal` | 4a + 4c (no voice) |
| Style demo / social one-liner | `--voice-only` | 4b + 4c (facts minimal) |

`--literal` and `--voice-only` are mutually exclusive (argparse-enforced).

## Synthesis writeback decision

Default = **skip**. Write a synthesis only when:

- The answer is genuinely cross-page (≥2 wiki pages contributed).
- A new comparison or explicit stance emerges that the wiki didn't yet hold.

Synthesis is not a knowledge-graph entry; it's an editorial crystallization.
Bad syntheses pollute future ask candidates. When in doubt, skip.

## ⚠️ 含未复核条目

If the orchestration message listed `needs_review: true` pages and the
answer cited any of them, prepend (above the disclaimer):

> ⚠️ 含未复核条目:本答案部分内容来自尚未与 ta 确认的页面。

This is mandatory — spec §6.3 step 8.

## Voice fallback

When `wiki/voice.md` doesn't exist:

- **default mode** auto-degrades to literal-style behavior. Don't read
  voice.md. Disclaimer becomes the literal-mode disclaimer.
- **voice-only mode** raises `FileNotFoundError` from `emit_prompt` — the
  user must run ingest first or switch to `--literal`.
- **literal mode** is unaffected.

## Exit / abort

Phase ask is single-shot. There's no "exit any time" — the user asked once,
you answer once, you call `ask-finish`. If you can't answer (vault has no
relevant material), output:

> 基于现有材料无法判断 — 请直接与 ta 确认。

followed by the disclaimer, then call `ask-finish` with
`--synthesis-written 0`.

## Don't

- Don't write voice content. `wiki/voice.md` is rebuilt only by ingest.
- Don't fabricate to fill style.
- Don't forget the disclaimer.
- Don't promote a single-source quote into a synthesis.
- Don't skip `ask-finish` — the log entry and auto-commit are required.
