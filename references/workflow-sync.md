# Sync Workflow

> **Audience:** Claude main conversation orchestrating Phase sync.

Note: Phase sync is mostly Python — `clonemate sync` runs the whole flow
end-to-end without a Claude pause. Claude is only invoked when sync is paired
with a follow-up `feed`/`ingest` for new raws.

## Triggers

1. **User-invoked**: `clonemate sync <slug> [--source X | --retry-failed]`.
2. **Cron / scheduled** (informational): user installs their own crontab line.

## Flow

1. profile_check.verify_profile — fails if vault profile mismatches lark-cli auth.
2. fetch_sources.run — per-source cursor isolation, failure isolation.
3. sync_cmd.finish — log + auto-commit.

## Don't

- Don't push the vault.
- Don't suggest re-clone on a single-source failure — `--retry-failed` is
  cheaper and preserves cursor state.
