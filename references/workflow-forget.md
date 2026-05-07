# Forget Workflow

> **Audience:** Claude main conversation orchestrating Phase forget.

## Three levels (spec §6.5)

| Level | Trigger | Effect | Confirmation |
|---|---|---|---|
| 1 — full vault | `clonemate forget <slug> --yes` | tomb + rm -rf + cross-vault syntheses scrub | `--yes` |
| 2 — single source | `clonemate forget <slug> --source <src-id>` then `forget-finish` | physical raw delete + Claude rewrites dirty wiki + filter-repo scrubs history | none for start; `--source` arg required |
| 3 — strong-gated rm | `clonemate forget <slug> --hard --yes-i-mean-it` | Same as Level 1 (rm vault + cross-vault syntheses scrub) but with stronger confirmation; for GDPR/compliance edge cases | `--hard` + `--yes-i-mean-it` |

## Level 2 flow (the only one that involves you)

1. User runs `clonemate forget <slug> --source <src-id>`.
2. Python:
   - physical-deletes `raw/.../src-id.md`
   - calls `pinned_fields_audit` (degrades confidence / clears pins)
   - emits prompt for you (Claude) listing dirty pages.
3. You:
   - Read each dirty page + remaining sources.
   - Rewrite per `references/prompt-forget.md`.
   - Use `merge_note.write(..., author_role='user')` with updated sources.
4. User runs `clonemate forget-finish --source <src-id>`:
   - commits your rewrites
   - runs `git filter-repo --replace-text` scrubbing the src-id from history
   - rebuilds index + logs + commits.

## Don't

- Don't run `forget-finish` until you've finished all dirty pages.
- Don't write to `wiki/voice.md` (M3 voice red line, M5 author guard).
- Don't try to recover the dropped src-id from git history — by design
  it's gone after `forget-finish` runs filter-repo.
- Don't suggest Level 3 unless the user explicitly cites GDPR /
  compliance — Level 1 + 2 cover almost everything.
