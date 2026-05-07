# Lint Workflow

> **Audience:** Claude main conversation orchestrating Phase lint.

## Triggers

1. **User-invoked**: `clonemate lint <slug>` directly.
2. **Scheduled**: `clonemate lint --schedule weekly` (informational; the user
   adds the crontab line themselves — skill never installs cron).

## Flow

1. Static scanners produce a `LintReport` (Python, pre-prompt).
2. Claude reads the report + runs the dynamic scan (per
   `references/prompt-lint.md`).
3. Claude surfaces findings in a Markdown report (no auto-fix).
4. Claude runs `lint-finish --findings <N>`.
5. User decides remediation: `clonemate review`, `clonemate forget`,
   or manual edit.

## Don't

- Don't auto-fix. Lint is read-only.
- Don't transition to forget — the user explicitly opts in.
- Don't write to wiki/voice.md.
