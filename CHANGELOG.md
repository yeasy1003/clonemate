# Changelog

## [0.1.0] - 2026-04-29

### M1 — 骨架 + sanitize 护栏

**Bootstrap (Phase A)**
- chore: pyproject.toml + .gitignore for clonemate skeleton
- chore: clonemate package skeleton + pytest conftest with `repo_root` / `empty_vault_dir` / `fake_lark_cli` fixtures
- docs: README, INSTALL, CONTRIBUTING, CHANGELOG, placeholders spec

**Sanitize Guard (Phase B)**
- feat(sanitize): default scans whole repo, with token/email/PII deny rules
- feat(sanitize): rules cover open_id / chat_id / app_id / union_id / message_id / object_id + docx / wiki / sheet / base / minute / file box tokens + emails (with `@example.{com,org,cn,io,test}` whitelist) + 18-digit ID card + 11-digit Chinese mobile
- feat(sanitize): line-level exemption via `# sanitize: allow-line <reason>`
- feat(sanitize): excluded dirs (`.git/`, `.venv/`, `__pycache__/`, etc.) + binary suffixes
- feat(sanitize): `main()` CLI returning exit 0 on clean / 1 on findings; repo self-scan test enforces clean repo

**git_ops (Phase C)**
- feat(git_ops): subprocess wrapper with `GitError` on nonzero exit
- feat(git_ops): `init_vault_repo` + `check_filter_repo` (raises `MissingDependencyError` if `git-filter-repo` missing)
- feat(git_ops): `install_pre_push_hook` for vault-local enforcement (refuses any push)

**vault (Phase D)**
- feat(vault): `init` creates directory tree (`raw/`, `wiki/{entities,concepts,syntheses,sources}/`), writes `_clone.yaml` (with `cursors` per source, `sources_enabled`, `window`, `quota`, `filters`), `index.md`, `log.md`, `SKILL.md`, `.clonemate-version`, vault `.gitignore` (excludes `raw/`); calls `git_ops.check_filter_repo` first, then `init_vault_repo`, then `install_pre_push_hook`
- feat(templates): `index.md.tmpl` / `SKILL.md.tmpl` / `persona.md.tmpl` / `voice.md.tmpl` / `_clone.yaml.tmpl`
- feat(vault): `list_vaults` enumerates vaults under a root by `_clone.yaml` presence
- feat(vault): `rename` moves dir + updates slug in `_clone.yaml`
- feat(vault): CLI `python -m clonemate.vault {init,list,rename}`

**Acceptance (Phase E)**
- docs: SKILL.md M1 draft (vault init only; ingest/query/lint deferred to M2+)
- chore: `.pre-commit-config.yaml` with ruff + sanitize_check
- feat: `install.sh` — clone, pip install, symlink, sanitize gate
- ci: GitHub Actions lint (ruff + mypy + sanitize) + unit (pytest)

## [Unreleased]

### v1.0 hardening track

- Real lark-cli integration tests (gated by profile / live API access)
- Dogfooding round across multiple colleagues
- OSS release prep: license review, CI matrix, contributor docs polish

## [0.7.0] - 2026-05-01

### M7 — Sync + Feed + Multi-profile (final M)

**Profile gating**
- feat(profile_check): verify_profile — sync/feed gate via lark-cli auth whoami (spec §8.7)

**sync_cmd**
- feat(sync_cmd): sync — wraps fetch_sources.run with profile gate + source/retry-failed filters (spec §6.6 / §8.7)
- feat(sync_cmd): finish — per-source log summary + auto-commit
- test(sync e2e): cursor isolation + skipped source recovery + idempotent (3 spec-required tests)

**feed_cmd + 9 parsers**
- feat(feed_parsers): registry + base contract
- feat(feed_parsers): text + fact parsers
- feat(feed_parsers): lark_doc + lark_sheet + lark_minutes URL parsers
- feat(feed_parsers): pdf + docx + pptx + html parsers (extras-gated)
- feat(feed_cmd): feed dispatcher + emit_prompt_for_ingest + feed_finish

**rebind + undo**
- feat(rebind_cmd): rebind — change vault profile when new profile shares app_id (spec §8.7)
- feat(undo_cmd): undo — git revert HEAD + index rebuild + log (spec §6.7)

**CLI**
- feat(cli): sync / sync-finish / feed / feed-finish / rebind / undo subcommands (M7 §6.6 / §6.2 / §8.7)

**Prompts**
- docs(prompt-feed): incremental ingest rubric for Phase feed
- docs(workflow-sync+workflow-feed): trigger / flow / don't lists

**Acceptance**
- test(e2e): feed pipeline plumbing — 5 tests

### Acceptance — v0.7.0 ship criteria

CloneMate v0.7.0 satisfies all spec §10 milestone criteria:
- M1 (skeleton + sanitize): `pip install -e .` works; sanitize-clean repo; vault init produces full tree.
- M2 (auto-collect): `clone <handle>` produces raw tree without writing wiki; failed sources don't block.
- M3 (ingest pipeline): fixed raw fixture → deterministic wiki tree; idempotent re-runs.
- M4 (review Phase B/C): conflict + ambiguity fixture walk-through; `pinned_fields` survive re-ingest.
- M5 (query + voice transfer): voice fidelity; disclaimer always present; no fact drift.
- M6 (lint + forget): hand-crafted fixtures detected; Level 2 forget proves `git log -p` clean of forgotten src.
- M7 (sync + feed): two syncs ≡ one wider-since clone (idempotent); cursor isolation across failures; per-parser feed paths green; profile mismatch reported clearly.

### Notes — M1-M7 complete

This is the **final milestone** of CloneMate v1. M1-M7 cover the full
Karpathy-LLM-Wiki spec (clone → ingest → review → query → lint → forget →
sync/feed). Next phase is hardening: more LLM-driven tests, real lark-cli
integration tests (gated by profile), and OSS release preparation.

- All Python modules remain LLM-free (spec §4.2). LLM work happens in Claude
  main conversation per `references/prompt-*.md`.
- Voice red line (spec §8.5) is structurally enforced by `merge_note` (M3)
  and reinforced by M5/M6 author guards.
- forget Level 2 history scrub uses `git-filter-repo`; see `references/workflow-forget.md`.
- Optional file parsers (pdf/docx/pptx/html) require extras: `pip install clonemate[pdf,docx,pptx,html]` or `pip install clonemate[all]`.

## [0.6.0] - 2026-05-01

### M6 — Lint + Forget

**Prereqs (Codex round 1 hardening)**
- feat(git_ops): rewrite_history_replace_text — wrap git filter-repo --replace-text for forget Level 2/3
- feat(vault): iter_vaults_under_root — list all vaults under a root for cross-vault ops
- feat(merge_note): forget_rewrite — replace-sources rewrite path that clears forget_dirty marker (Codex round 1 Findings 2+3+7)
- feat(forget_state): durable dirty state for Level 2 crash recovery (Codex round 1 Findings 2+4+6)

**lint_cmd (Phase lint)**
- feat(lint_cmd): LintReport + 4 finding dataclasses
- feat(lint_cmd): scan_orphan_pages — wiki pages absent from index.md
- feat(lint_cmd): scan_missing_sources_pages — wiki pages with empty/missing frontmatter sources
- feat(lint_cmd): scan_dead_refs — wiki frontmatter mentions src-XXX with no matching raw file
- feat(lint_cmd): scan_stale_pages — wiki pages with last_modified > 90d ago
- feat(lint_cmd): build_report — aggregate all 4 lint buckets
- feat(lint_cmd): emit_prompt — Claude orchestration for static + dynamic lint
- feat(lint_cmd): finish — log lint run + auto-commit

**forget_cmd + cross_vault**
- feat(forget_cmd): forget_level1 — tomb marker + rm -rf + cross-vault scrub stub
- feat(cross_vault): scrub_slug_from_syntheses — replace cross-vault refs with placeholder on Level 1 forget
- feat(forget_cmd): identify_dirty_pages — wiki pages referencing a src_id slated for forget
- feat(forget_cmd): pinned_fields_audit — degrade confidence or clear pins when src support drops (spec §6.5 step 3)
- feat(forget_cmd): forget_level2_start — physical raw delete + dirty mark + audit + emit prompt
- feat(forget_cmd): forget_level2_finish — filter-repo scrub + index rebuild + log + commit
- feat(forget_cmd): forget_level3_hard — Level 1 with stronger confirmation gate (--yes-i-mean-it required; spec §6.5 GDPR fallback)

**CLI**
- feat(cli): lint / lint-finish / forget / forget-finish subcommands (M6 §6.4 + §6.5)

**Prompts**
- docs(prompt-lint): Phase lint dynamic-scan rubric (4 dimensions)
- docs(prompt-forget): Phase forget Level 2 dirty-page rewrite rubric
- docs(workflow-lint+workflow-forget): trigger / flow / don't lists for M6 ops

**Acceptance**
- test(fixtures): m6 lint + m6 forget input vaults
- test(e2e): lint + forget pipeline plumbing — 13 tests covering all paths

### Notes

- M6 delivers lint (read-only) and forget (Level 1 / 2 / 3). M7 sync/feed remains.
- All M6 Python modules remain LLM-free (spec §4.2). Dynamic lint and dirty-page rewrite are Claude-driven via `references/prompt-lint.md` / `references/prompt-forget.md`.
- `git filter-repo` is now a hard runtime dependency for forget Level 2 / 3 (declared in M1's `vault init`).
- Forget Level 2 commit message uses `(forgotten)` placeholder to avoid leaking the src-id into the post-scrub commit log.

## [0.5.0] - 2026-04-30

(Same-day release as v0.4.0 — M4 landed earlier in the day, M5 followed in the same session per spec §10 "每个 M 串行完成,~3-7 天纯工作量".)

### M5 — Query + voice transfer

**merge_note (M3 prereq hardening — Codex rounds 1+3 findings)**
- feat(merge_note): voice red-line — only author_role='ingest' may write page_type='voice' (Codex round 1 Finding 1)
- feat(merge_note): byte-equal idempotency — same body + sources + confidence + needs_review is a no-op (Codex round 1 Finding 6 / round 3 Finding A)
- feat(merge_note): voice_md_is_valid helper — frontmatter-parsing voice.md sanity check (Codex round 1 Finding 5)
- feat(merge_note): _validate_title — reject whitespace-only / overlong / reserved-name titles (Codex round 3 Finding D)

**query_cmd (Phase ask)**
- feat(query_cmd): emit_prompt default mode — 4a/4b/4c orchestration message
- feat(query_cmd): emit_prompt --literal mode — facts-only neutral output
- feat(query_cmd): emit_prompt --voice-only mode — style fidelity > fact completeness
- feat(query_cmd): emit_prompt warns when wiki has needs_review pages (spec §6.3 step 8)
- feat(query_cmd): emit_prompt voice.md fallback — default→literal, voice-only→raise
- feat(query_cmd): finish — log query + auto-commit
- feat(query_cmd): finish writes synthesis path — index rebuilt + log entry
- test(query_cmd): finish auto-commit semantics — HEAD advances + identity fallback + empty-diff no-op

**CLI**
- feat(cli): ask subcommand — emit Phase ask prompt with mode flags
- feat(cli): ask-finish subcommand — log + index rebuild + auto-commit

**Prompts**
- docs(prompt-query): Phase ask 4a/4b/4c rubric + 3-mode behavior table
- docs(workflow-query): trigger / writeback decision / fallback / exit
- docs(prompt-ingest): note that M5 ask is now available (not auto-chained)

**Acceptance**
- test(fixtures): m5 query input vault — voice + persona + entity + 1 needs_review concept
- test(e2e): query pipeline plumbing — 12 tests covering mode dispatch / synthesis writeback / log sanitization

### Notes

- M5 delivers Phase ask only. **M6 lint/forget** + **M7 sync/feed** still ahead.
- All M5 Python modules remain LLM-free (spec §4.2). LLM work is in Claude main conversation per `references/prompt-query.md`.
- Synthesis writeback is **opt-in** — default behavior is to skip; only crystallize true cross-page comparisons.
- Voice red line (spec §8.5) is structurally enforced by `merge_note` (M3); M5 only generates prompts that remind Claude.

## [0.4.0] - 2026-04-30

### M4 — Phase B/C 引导式确认

**review_cmd (Phase B scanner)**
- feat(review_cmd): ReviewChecklist + 4 item dataclasses (ConflictItem / NeedsReviewItem / AmbiguityItem / UnclearTopicItem)
- feat(review_cmd): scan_conflicts — find inline ⚠️ CONFLICT markers
- feat(review_cmd): scan_needs_review — frontmatter-driven needs_review pages
- feat(review_cmd): scan_ambiguities + scan_unclear_topics — inline ⚠️ markers
- feat(review_cmd): build_checklist — aggregate all 4 review buckets
- feat(review_cmd): emit_prompt — orchestration message for Phase B/C
- feat(review_cmd): finish — rebuild index + append log after Phase C

**merge_note (M4 additions)**
- feat(merge_note): resolve_conflict — replace section + drop ⚠️ CONFLICT marker
- feat(merge_note): apply_review_accept — flip needs_review false + optional confidence promote + pin

**CLI (Phase E)**
- feat(cli): review + review-finish subcommands

**Prompts (Phase D)**
- docs(prompt-review): Phase B/C dialogue script (4-option per item)
- docs(prompt-conflict): user-driven conflict resolution sub-flow
- docs(workflow-review): trigger / continue / exit contract
- docs(prompt-ingest): hand off to Phase B/C after ingest-finish

**Acceptance (Phase E)**
- test(fixtures): m4 review input vault
- test(e2e): review pipeline plumbing — 7 tests covering build/apply/skip/empty

### Notes

- M4 delivers Phase B/C only. **M5 voice transfer answer** + **M6 lint/forget** + **M7 sync/feed** still ahead.
- All M4 Python modules remain LLM-free (spec §4.2). LLM work is in Claude main conversation per `references/prompt-review.md`.
- Skipped items remain `[需复核]` and resurface in the next `clonemate review` pass.

## [0.3.0] - 2026-04-30

### M3 — Ingest pipeline + voice 提炼

**Foundation (Phase A)**
- feat(log_append): append-only timeline with grep-friendly format
- docs(wiki-schema): full page-type / frontmatter / voice / conflict spec for M3 ingest

**merge_note (Phase B) — wiki single-writer entry-point**
- feat(merge_note): atomic wiki writer skeleton + frontmatter validation
- feat(merge_note): preserve pinned_fields sections across re-ingest (spec §3 decision 10)
- feat(merge_note): voice red-line — reject disallowed source_types per spec §8.5
- feat(merge_note): per-page fcntl.flock for concurrent subagent safety
- feat(merge_note): pin / unpin convenience helpers

**index_upsert (Phase C)**
- feat(index_upsert): scan_wiki — read pages + count needs_review/conflicts
- feat(index_upsert): rebuild — render full index.md with triage / persona / voice / entities / concepts / syntheses / sources
- feat(index_upsert): update_page — incremental rebuild after single-page write
- feat(index_upsert): CLI for ad-hoc rebuild
- feat(index_upsert): optional log_append on rebuild for audit trail

**Prompts (Phase D)**
- docs(prompt-ingest): Phase A silent ingest orchestration prompt
- docs(prompt-voice): subagent prompt for voice extraction with author filter (spec §3 decision 18)
- docs(workflow-ingest): subagent dispatch matrix + idempotency contract

**Orchestration (Phase E)**
- feat(ingest_cmd): list_raw — group raw files by source_type
- feat(ingest_cmd): emit_prompt — builds the orchestration message for Claude main conversation
- feat(ingest_cmd): finish — rebuild index + append log after subagents
- feat(cli): ingest + ingest-finish subcommands

**Acceptance (Phase F)**
- test(fixtures): m3 ingest input vault — contact + im_1v1 with full author_open_id
- test(e2e): ingest pipeline plumbing — fake subagents exercise merge_note, voice red-line, sources union, pinned carry-forward (4 real tests, run in CI)

### Notes

- M3 delivers Phase A static ingest only. **Phase B 复核清单 + Phase C 引导式确认 are M4.**
- **Voice transfer answer is M5** (this milestone only writes voice.md as input for M5).
- All Python modules in M3 are LLM-free (spec §4.2 contract). LLM work happens in Claude main conversation per `references/prompt-ingest.md` + `references/workflow-ingest.md`.
- Per-page fcntl.flock is POSIX-only; Windows is not a v1 target.

## [0.2.0] - 2026-04-30

### M2 — 自动采集 + raw dump

**Foundation utilities (Phase A)**
- feat(parse_since): unified `--since` parser (`180d` / `1y` / `YYYY-MM-DD`, default 180d)
- feat(lark_cli): subprocess wrapper with JSON parse + `LarkCliError`
- feat(content_hash): normalised SHA256 for raw dedup
- feat(raw_writer): `RawCandidate` + write with src_id assignment + per-source-type hash dedup

**Identity (Phase B)**
- feat(resolve): handle → `Candidate(open_id, app_id, display_name, email)`
  (open_id passthrough / email / name search; multiple candidates on collision)

**Adapter foundation (Phase C)**
- feat(adapters): `_base` Protocol + `FetchContext` + `AdapterResult`
- feat(plugins): entry-points discovery with `plugins_allowed` white-list

**Source adapters (Phase D)**
- feat(adapters): contact (single profile)
- feat(adapters): im_1v1 (per-month partition + author_open_id per message + cursor)
- feat(adapters): im_group (signal filter — self/mention/quoted — + ±20 context + author_open_id)
- feat(adapters): minutes (owner+participant merge dedup + ta transcript only)
- feat(adapters): docs_owned — markdown body download per doc + per-source MB quota (raw is source of truth, spec §3.1)
- feat(adapters): doc_comments (per-comment author_open_id + per-doc cursor)
- feat(adapters): calendar_titles (white-list summary/time/participants only — privacy red-line)
- feat(adapters): meego stub (defers to clonemate.sources entry-point plugin)

**Orchestration (Phase E)**
- feat(fetch_sources): per-source cursor advance only on full success
- feat(fetch_sources): failed source preserves cursor + writes `.error.log`
- feat(fetch_sources): quota-skipped source records `skipped_reason`
- feat(fetch_sources): chains `docs_owned` tokens into `doc_comments` cursor

**CLI (Phase F)**
- feat(clone_cmd): end-to-end orchestrator (resolve → vault.init → fetch_sources)
- feat(cli): `python -m clonemate clone <handle>` entry

### Notes
- M2 ships **sequential** source execution; parallel execution is a future optimisation.
- M2 raw paths are **hash-suffixed** (`<stem>-<8 hex chars>.md`) so two syncs of the same logical partition (e.g. same `<chat_id>/<yyyy-mm>` with different message batches) coexist as separate immutable files. spec §3.1: raw 不可变.
- M2 does **NOT** write any wiki / index / log content — that begins in M3.
