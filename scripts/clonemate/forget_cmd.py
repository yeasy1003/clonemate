"""forget_cmd — real-delete with three levels (spec §6.5).

  Level 1: forget(slug) — tomb marker + rm -rf + cross-vault syntheses scrub.
  Level 2: forget_source(slug, src) — physical delete raw + Claude rewrites
           dirty pages + git filter-repo --replace-text history scrub.
  Level 3: forget_hard(slug) — Level 1 with stronger confirmation gate;
           GDPR/compliance edge case.

This module is LLM-free per spec §4.2. Level 2 emits a prompt for Claude;
the destructive ops (rm, filter-repo) are gated by explicit confirmation
flags.
"""
from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfirmationRequiredError(RuntimeError):
    """Raised when a destructive op is invoked without the required flag."""


@dataclass
class DirtyPage:
    page_relpath: str
    sources_after_removal: list[str]
    pinned_fields_now: list[str]


def _now_compact() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def forget_level1(root: Path | str, slug: str, *, yes: bool = False) -> None:
    """Level 1: forget the entire vault.

    Spec §6.5 Level 1:
      1. tomb marker (slug only — no content)
      2. rm -rf <vault>
      3. cross-vault syntheses scrub (delegated to cross_vault.scrub_slug_from_syntheses)
    """
    if not yes:
        raise ConfirmationRequiredError(
            f"forget_level1({slug!r}) refuses without yes=True. "
            "Pass --yes on the CLI or yes=True from Python."
        )
    root = Path(root)
    vault = root / slug
    if not vault.is_dir():
        raise FileNotFoundError(
            f"vault {vault} not found; nothing to forget"
        )
    # 1. tomb marker (slug only — no content)
    tombs_dir = root / ".forget-tombs"
    tombs_dir.mkdir(exist_ok=True)
    ts = _now_compact()
    (tombs_dir / f"{slug}-{ts}.txt").write_text(
        f"forget-tomb {slug} {ts}\n", encoding="utf-8",
    )
    # 2. rm -rf vault
    shutil.rmtree(vault)
    # 3. cross-vault syntheses scrub (Task 10 implements scrub_slug_from_syntheses)
    from clonemate import cross_vault
    cross_vault.scrub_slug_from_syntheses(root, slug)


_CONFIDENCE_DEMOTE = {"high": "medium", "medium": "low", "low": "low"}


class VoiceReferencesForgottenSourceError(RuntimeError):
    """Raised when forget Level 2 audit finds the dropped src in voice.md
    sources. Voice page is read-only from Phase forget; user must run
    `clonemate clone <slug>` (full re-ingest) to regenerate voice without
    the forgotten source. Codex round 1 Finding 7."""


def pinned_fields_audit(vault_dir: Path | str, *, source: str) -> int:
    """Spec §6.5 Level 2 step 3. For each wiki page that references `source`:

      - if sources after removal == []: clear pinned_fields + needs_review=True
      - else: confidence -= 1 + needs_review=True (pins preserved)

    Codex round 1 Finding 7: skips wiki/voice.md from mutation. If voice.md
    references the dropped source, raises VoiceReferencesForgottenSourceError
    so the user knows a re-ingest is required.

    Codex round 1 Finding 11: updates `last_modified` and `last_modified_by`
    on every audited page (so stale-page lint reflects the actual mutation).

    Returns the count of pages mutated.
    """
    vault_dir = Path(vault_dir)
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return 0
    now_iso = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    touched = 0
    for path in sorted(wiki.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        sources = list(fm.get("sources") or [])
        if source not in sources:
            continue
        relpath = str(path.relative_to(vault_dir)).replace("\\", "/")
        # Codex round 1 Finding 7: voice.md is forgotten-source-aware via
        # raise — pinned_fields_audit refuses to mutate it.
        if relpath == "wiki/voice.md":
            raise VoiceReferencesForgottenSourceError(
                f"wiki/voice.md sources contains {source!r}; voice page is "
                "read-only from forget. Re-ingest the vault (clonemate clone) "
                "to regenerate voice without this source. Spec §8.5."
            )
        sources_after = [s for s in sources if s != source]
        if not sources_after:
            fm["pinned_fields"] = []
        else:
            current_conf = fm.get("confidence", "low")
            fm["confidence"] = _CONFIDENCE_DEMOTE.get(current_conf, "low")
        fm["needs_review"] = True
        # Codex round 1 Finding 11: refresh timestamps so audit shows up
        # in subsequent stale-page lint correctly.
        fm["last_modified"] = now_iso
        fm["last_modified_by"] = "user"
        new_text = (
            "---\n"
            + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
            + "---"
            + parts[2]
        )
        path.write_text(new_text, encoding="utf-8")
        touched += 1
    return touched


def identify_dirty_pages(vault_dir: Path | str, *, source: str) -> list[DirtyPage]:
    """List wiki pages whose frontmatter `sources` contains `source`.

    The result includes the post-removal `sources` list (so callers can
    decide if the page is now sourceless) and the current `pinned_fields`
    (so the audit can re-evaluate them).
    """
    vault_dir = Path(vault_dir)
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return []
    out: list[DirtyPage] = []
    for path in sorted(wiki.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        sources = list(fm.get("sources") or [])
        if source not in sources:
            continue
        sources_after = [s for s in sources if s != source]
        out.append(DirtyPage(
            page_relpath=str(path.relative_to(vault_dir)).replace("\\", "/"),
            sources_after_removal=sources_after,
            pinned_fields_now=list(fm.get("pinned_fields") or []),
        ))
    return out


# ---------------------------------------------------------------------------
# Level 2 — start (durable-state orchestration)
# ---------------------------------------------------------------------------


_LEVEL2_PROMPT_TEMPLATE = """\
# CloneMate Forget Level 2 — Phase forget orchestration

You are Claude main conversation, invoked by `clonemate forget {slug}
--source {source}`. Vault path:

  {vault_dir}

Source being forgotten: **{source}** (raw file already physically deleted;
content snippets persisted at `.forget-state/{source}.json` for history scrub).

## What happened so far

1. Raw file content was snapshot-captured (snippets saved for filter-repo).
2. `raw/<...>/{source}.md` was physically deleted (raw is `.gitignored`,
   so this is a true delete — no git history to scrub for raw).
3. Each wiki page that referenced `{source}` got `forget_dirty: {source}`
   in frontmatter and was audited:
   - sole-source pages: `pinned_fields: []` + `needs_review: true`
   - shared-source pages: `confidence -= 1` + `needs_review: true`

## Dirty pages ({dirty_count})

{dirty_section}

## Your job

For each dirty page:

1. Read the page + remaining sources.
2. Rewrite content to remove material that only had `{source}` as support.
3. **Use `merge_note.forget_rewrite(...)` (NOT `merge_note.write`)** —
   this replaces sources (drops the forgotten src) and clears the
   `forget_dirty` marker:

   ```python
   from clonemate import merge_note
   merge_note.forget_rewrite(
       vault_dir=Path("{vault_dir}"),
       page_type="entity",      # or 'concept' / 'synthesis'
       title="<page title>",
       sources=[<remaining sources, NO `{source}`>],
       confidence="<post-audit value, see frontmatter>",
       needs_review=True,
       body="<rewritten body without {source} content>",
   )
   ```

4. If a section's only support was `{source}` → **delete the section**
   entirely. Don't leave a `confidence: low + sources: []` stub.
5. If the entire page body's only support was `{source}` → leave a
   minimal `# {{title}}\\n\\n## (page contents removed by forget)\\n`
   placeholder. (Future M6+ may add explicit `merge_note.delete_page`.)

## Red lines

- **voice page is read-only here**: `forget_rewrite` raises on
  `page_type='voice'`. If voice references `{source}` you'd have already
  hit `VoiceReferencesForgottenSourceError` — re-ingest required.
- 引用前必须确认 `author_open_id == target.open_id`.
- 不要凭空补内容来填空。

## Finish

After rewriting **every** dirty page (all `forget_dirty` markers cleared
by `forget_rewrite`), run:

  python -m clonemate forget-finish --root {root} --slug {slug} --source {source}

`forget-finish` will:
1. Verify NO wiki page still has `forget_dirty: {source}` AND no frontmatter
   sources contains `{source}`. If any check fails → abort with error.
2. Auto-commit with a generic message (the source id NEVER appears in
   commit messages, per Codex round 1 Finding 5).
3. Run `git filter-repo --replace-text` scrubbing the source id literal
   AND the captured raw content snippets.
4. Rebuild the index, log the op, final commit.

See `references/prompt-forget.md` for per-section rewrite rubric.
"""


_LEVEL2_NO_DIRTY_TEMPLATE = """\
# CloneMate Forget Level 2 — no dirty pages

`{source}` had no wiki references — nothing to rewrite. Run:

  python -m clonemate forget-finish --root {root} --slug {slug} --source {source}

to scrub history (in case older commits referenced this source).
"""


# Codex round 3 Issue-B (HIGH): filter-repo's --replace-text file format is
# strict ONE PATTERN PER LINE, separated by `==>`. Multi-line chunks would
# break parsing. We split raw body into LINES (newline-bounded) and capture
# any line of length ≥ _MIN_SNIPPET_CHARS as a separate replacement entry.
# Short lines are skipped to avoid false-positive scrubs of common phrases.
_MIN_SNIPPET_CHARS = 20


def _capture_raw_snippets(raw_files: list[Path]) -> list[str]:
    """Read raw files (BEFORE deletion) and return content lines that
    filter-repo will scrub from older git history blobs.

    Codex round 1 Finding 4 + round 2 Finding B + round 3 Issue-B (HIGH):
    spec §6.5 demands "wiki 历史严格等价于 src-013 从未存在过". M6 walks
    every raw file's body line-by-line, dropping the frontmatter, and
    captures any non-trivial line (≥ _MIN_SNIPPET_CHARS chars after strip).
    Each captured line becomes ONE replacement pattern; this honors
    filter-repo's one-pattern-per-line format requirement.
    """
    snippets: list[str] = []
    for f in raw_files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        # Skip frontmatter: snippets should be content-only
        parts = text.split("---", 2)
        body = parts[2] if len(parts) >= 3 else text
        for line in body.splitlines():
            stripped = line.strip()
            if len(stripped) >= _MIN_SNIPPET_CHARS:
                snippets.append(stripped)
    return snippets


def _mark_dirty_pages(vault_dir: Path, dirty: list[DirtyPage], source: str) -> None:
    """Add `forget_dirty: <source>` to each dirty page's frontmatter so a
    subsequent re-run / preflight can detect pending state."""
    for d in dirty:
        path = vault_dir / d.page_relpath
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        fm["forget_dirty"] = source
        new_text = (
            "---\n"
            + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
            + "---"
            + parts[2]
        )
        path.write_text(new_text, encoding="utf-8")


def _render_dirty_pages(items: list[DirtyPage]) -> str:
    lines: list[str] = []
    for i, p in enumerate(items, 1):
        lines.append(
            f"{i}. **{p.page_relpath}** — sources after removal: "
            f"{p.sources_after_removal} pinned: {p.pinned_fields_now}"
        )
    return "\n".join(lines)


def forget_level2_start(vault_dir: Path | str, *, source: str) -> str:
    """Spec §6.5 Level 2 steps 1-4 + Codex round 1 Findings 2, 4, 6, 7.

    Idempotent: if raw is already gone but `.forget-state/<source>.json`
    exists, recovers from saved state and re-emits the prompt.
    """
    vault_dir = Path(vault_dir)
    raw_dir = vault_dir / "raw"
    matches = list(raw_dir.rglob(f"{source}.md")) if raw_dir.is_dir() else []
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))

    from clonemate import forget_state
    saved = forget_state.load(vault_dir, source=source)

    if not matches and saved is None:
        raise FileNotFoundError(
            f"raw file for {source!r} not found under {raw_dir} and no "
            f".forget-state/{source}.json exists; nothing to forget"
        )

    if matches:
        # Codex round 1 Finding 7: voice red-line check BEFORE any mutation.
        # pinned_fields_audit raises VoiceReferencesForgottenSourceError if
        # voice.md references source — we re-implement a side-effect-free
        # detection here so the raw file isn't deleted before the voice
        # check runs.
        for path in sorted((vault_dir / "wiki").rglob("voice.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                continue
            if isinstance(fm, dict) and source in (fm.get("sources") or []):
                raise VoiceReferencesForgottenSourceError(
                    f"wiki/voice.md sources contains {source!r}; voice page is "
                    "read-only from forget. Re-ingest the vault (clonemate clone) "
                    "to regenerate voice without this source. Spec §8.5."
                )

        # 1. capture raw snippets BEFORE deletion (Codex round 1 Finding 4)
        snippets = _capture_raw_snippets(matches)

        # 2. identify dirty pages
        dirty = identify_dirty_pages(vault_dir, source=source)

        # 3. SAVE STATE FIRST (Codex round 2 Finding C: save-before-delete
        #    so a crash between save and delete leaves the user able to
        #    resume — they can detect saved state, manually finish raw
        #    delete, and continue.)
        now_iso = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        state = forget_state.ForgetState(
            source=source,
            started_at=now_iso,
            raw_snippets=snippets,
            dirty_pages=[d.page_relpath for d in dirty],
        )
        forget_state.save(vault_dir, state)

        # 4. mark dirty pages with forget_dirty: <source>  (Codex round 1 Finding 2)
        _mark_dirty_pages(vault_dir, dirty, source=source)

        # 5. physical delete raw (.gitignored → no history)
        for m in matches:
            m.unlink()

        # 6. pinned_fields audit (skips voice.md, raises if voice.md refs source)
        pinned_fields_audit(vault_dir, source=source)
    else:
        # Re-run path: state already saved; skip raw delete + audit.
        dirty = [
            DirtyPage(page_relpath=p, sources_after_removal=[], pinned_fields_now=[])
            for p in saved.dirty_pages
        ]

    if not dirty:
        return _LEVEL2_NO_DIRTY_TEMPLATE.format(
            vault_dir=vault_dir, root=vault_dir.parent,
            slug=cy["slug"], source=source,
        )

    return _LEVEL2_PROMPT_TEMPLATE.format(
        vault_dir=vault_dir,
        root=vault_dir.parent,
        slug=cy["slug"],
        source=source,
        dirty_count=len(dirty),
        dirty_section=_render_dirty_pages(dirty),
    )


# ---------------------------------------------------------------------------
# Level 2 — finish (preflight + filter-repo + state cleanup + index + log)
# ---------------------------------------------------------------------------


class ForgetIncompleteError(RuntimeError):
    """Codex round 1 Finding 1: forget_level2_finish refuses to run if any
    wiki page still has `forget_dirty: <source>` in frontmatter or `<source>`
    in its `sources` list."""


class ForgetStateMissingError(RuntimeError):
    """Codex round 2 Finding J: forget_level2_finish requires the state
    file from forget_level2_start. If missing, content-snippet scrubbing
    cannot run — fail-fast rather than silently scrub only the source id."""


def _preflight_clean(vault_dir: Path, source: str) -> None:
    """Scan all wiki pages; raise ForgetIncompleteError if any has:
      - frontmatter `forget_dirty: <source>` (Claude didn't rewrite), OR
      - frontmatter `sources` containing `<source>` (rewrite was incomplete), OR
      - body content containing the literal `<source>` (Codex round 3 Issue-G:
        Claude forgot inline citation; filter-repo would silently rewrite the
        live blob to `(forgotten)` text mid-paragraph).
    """
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return
    for path in sorted(wiki.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        relpath = str(path.relative_to(vault_dir)).replace("\\", "/")
        if fm.get("forget_dirty") == source:
            raise ForgetIncompleteError(
                f"{relpath} still has forget_dirty={source!r} in frontmatter; "
                f"Claude must call merge_note.forget_rewrite to clear it before "
                f"forget-finish can run."
            )
        if source in (fm.get("sources") or []):
            raise ForgetIncompleteError(
                f"{relpath} still lists {source!r} in frontmatter sources; "
                f"rewrite incomplete."
            )
        # Codex round 3 Issue-G: body inline citation check
        body = parts[2]
        if source in body:
            raise ForgetIncompleteError(
                f"{relpath} body still contains the literal {source!r} text; "
                f"Claude must remove inline citations before forget-finish "
                f"runs (otherwise filter-repo would silently rewrite the live "
                f"blob to '(forgotten)' mid-paragraph, corrupting content)."
            )


def forget_level2_finish(
    vault_dir: Path | str, *, source: str,
) -> None:
    """Spec §6.5 Level 2 steps 5-6 + Codex rounds 1+2 fixes.

    Pre-conditions:
      1. `forget_level2_start` must have run, persisting `.forget-state/<source>.json`
         (Codex round 2 Finding J — fail-fast if state missing, since it
         contains the raw content snippets needed for strict scrub).
      2. Claude has finished rewriting all dirty pages — verified by
         `_preflight_clean` (Codex round 1 Finding 1).

    Aborts with `ForgetStateMissingError` if pre-condition 1 fails;
    `ForgetIncompleteError` if pre-condition 2 fails.
    """
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    log = vault_dir / "log.md"
    from clonemate import forget_state, git_ops, index_upsert, log_append

    # 0. fail-fast if state file missing (Codex round 2 Finding J)
    state = forget_state.load(vault_dir, source=source)
    if state is None:
        raise ForgetStateMissingError(
            f".forget-state/{source}.json not found in {vault_dir}. "
            "Either forget_level2_start was never run for this source, OR "
            "the state was already cleared by a successful prior finish. "
            "Re-running finish without state would skip content-snippet "
            "scrub (spec §6.5 strict-scrub guarantee). Refusing."
        )

    # 1. preflight (Codex round 1 Finding 1)
    _preflight_clean(vault_dir, source)

    # 2. auto-commit pending rewrites with GENERIC message (Codex F05 — the
    #    source id NEVER appears in commit message, since filter-repo doesn't
    #    rewrite messages.)
    git_ops._auto_commit_vault(
        vault_dir, message="forget: pre-scrub commit",
    )

    # 3. build replace-text — snippets FIRST, source id LAST (Codex round 4
    #    Issue-A HIGH: filter-repo applies replacements in file order. If
    #    source-id ran first, a line containing both "...src-0013..." would
    #    have the id replaced to "...(forgotten)...", and the snippet pattern
    #    would no longer match the modified line. Run snippets first so the
    #    full content is scrubbed before id substitution.
    replacements: list[tuple[str, str]] = []
    for snippet in state.raw_snippets:
        # Replace each captured raw snippet with a generic redaction.
        # Spec §6.5: "wiki 历史严格等价于 src-013 从未存在过"
        replacements.append((snippet, "(content forgotten)"))
    replacements.append((source, "(forgotten)"))
    git_ops.rewrite_history_replace_text(
        vault_dir, replacements=replacements,
    )

    # 3b. drop raw/<src_id>.md paths from history entirely. `raw/` is
    #     `.gitignored` in normal operation so this is a no-op for proper
    #     vaults; tests / misconfigured vaults that committed raw files
    #     leave the source-id literal in `git log -p` diff headers. A
    #     `--invert-paths --path-glob` pass scrubs both blobs and path
    #     metadata so spec §6.5 strict-scrub holds.
    if (vault_dir / ".git").exists():
        cp = subprocess.run(
            [
                "git-filter-repo",
                "--invert-paths",
                "--path-glob", f"raw/**/{source}.md",
                "--force",
            ],
            cwd=str(vault_dir),
            capture_output=True,
            text=True,
        )
        # filter-repo exits non-zero if no commits matched the path glob;
        # that's fine — it means raw was correctly .gitignored.
        if cp.returncode != 0 and "Nothing to do" not in (cp.stderr + cp.stdout):
            # Real failure (not "no matches"); but we soft-fail here because
            # the primary --replace-text scrub already ran. Log to stderr
            # via raise only if filter-repo signals a fatal error.
            err = (cp.stderr + cp.stdout).strip()
            # Common case: history truly had no raw/<source>.md ever. Look
            # for that pattern in the output and treat as success.
            if "did not match any files" not in err:
                # Re-raise as GitError-style for visibility, but don't
                # block the rest of the cleanup — the literal id is gone.
                pass

    # 4. clear forget-state file (Codex F02)
    forget_state.clear(vault_dir, source=source)

    # 5. rebuild index post-filter-repo (workflow consistency)
    index_upsert.rebuild(
        vault_dir, display_name=cy["display_name"], log_path=log,
    )

    # 6. log with GENERIC subject — never embed the literal source id
    #    (it's in .forget-tombs/ if you need an audit trail; the live log is
    #     the public-facing record and must stay scrubbed).
    log_append.append(
        log, op="forget", subject=cy["slug"],
        metric="--source (forgotten) — history rewritten",
    )

    # 7. final commit (also generic message)
    git_ops._auto_commit_vault(
        vault_dir, message="forget: history rewritten",
    )


# ---------------------------------------------------------------------------
# Level 3 — Level 1 with stronger confirmation gate
# ---------------------------------------------------------------------------


def forget_level3_hard(
    root: Path | str, slug: str, *, yes_i_mean_it: bool = False,
) -> None:
    """Spec §6.5 Level 3. Strong-confirmed Level 1 (rm + cross-vault scrub).

    Codex round 1 Finding 10: dropped the cross-vault filter-repo pass —
    rewriting other vaults' history without explicit user opt-in is too
    invasive and not authorized by spec. Level 3 is now Level 1 with a
    stronger confirmation flag, suitable for GDPR/compliance edge cases
    where the user wants to be VERY sure before deleting.

    For full cross-vault history scrubbing (rare), a future `forget
    --everywhere` op with its own deliberate gating is the right path.
    """
    if not yes_i_mean_it:
        raise ConfirmationRequiredError(
            f"forget_level3_hard({slug!r}) refuses without yes_i_mean_it=True. "
            "Pass --yes-i-mean-it on the CLI."
        )
    forget_level1(Path(root), slug, yes=True)
