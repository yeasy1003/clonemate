# Review Workflow

> **Audience:** Claude main conversation orchestrating M4 Phase B/C.

## Triggers

Phase B/C runs in three situations:

1. **Auto-continue after ingest** — `prompt-ingest.md` ends with a handoff to
   read `prompt-review.md`. After `clonemate ingest-finish`, immediately:
   ```
   python -m clonemate review --root <root> --slug <slug>
   ```
   then drive Phase C dialogue.

2. **User-invoked** — `clonemate review <slug>` directly. Same flow.

3. **Feed-triggered (M4 partial)** — When a single `clonemate feed` produces
   a conflict OR touches a persona core field, `feed_cmd` (M7) emits a
   focused mini-review prompt. M4 does not yet implement feed; the workflow
   is documented here so M7 can hook in.

## Continuation contract

- The orchestration message from `review_cmd.emit_prompt` is **structured** —
  Claude reads the checklist and runs the per-item dialogue from
  `prompt-review.md`. Conflict items go through `prompt-conflict.md`.
- Each user decision applied → next item.
- Empty checklist → tell user "无需复核" → run `review-finish` with 0/0.

## Exit handling

User can exit any time by saying "够了 / 跳过剩下 / 下次再说". On exit:
1. Tell the user "好,剩 N 条留 `[需复核]`,下次跑 `clonemate review` 继续"
2. Run `python -m clonemate review-finish --resolved K --skipped N`

## Idempotency

Running `clonemate review` twice in a row should:
- 1st run: surface all current checklist items
- After user resolves K, skips N
- 2nd run: surface only the N skipped items + any new conflicts that appeared
  via concurrent ingest (rare; the next clonemate ingest may add new ones)

## Don't

- Don't push past user's exit — Phase B/C is **user-driven**, not exhaustive.
- Don't pin a field without explicit user confirmation (option [A] for persona
  core fields with pin_fields).
- Don't change voice page content — voice is rebuilt only by ingest (Phase A);
  Phase C may pin voice attributes via `pin_fields=["..."]` but won't rewrite body.
