"""feed_cmd — dispatch external content to a parser, write raw, then emit
prompt for Claude to run incremental ingest. Spec §6.2."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from clonemate import feed_parsers, profile_check
from clonemate.feed_parsers._base import ParserUnavailable as _ParserUnavailable
from clonemate.raw_writer import RawWriter


class NoParserError(RuntimeError):
    """Raised when no parser can_handle the input AND no extras-install hint applies.
    For extras-gated parsers whose dep is missing, ParserUnavailable is raised instead."""


# Re-export for CLI ergonomics — `feed_cmd.ParserUnavailable` works.
ParserUnavailable = _ParserUnavailable


@dataclass
class FeedResult:
    parser_name: str
    raws_written: int = 0
    raw_paths: list[str] = field(default_factory=list)
    # Codex round 1 Finding 12: surface fact-mode write outcome so the CLI
    # can warn on title collision instead of silently masking conflicts.
    wiki_path_written: str | None = None
    was_idempotent_no_op: bool = False


def feed(
    vault_dir: Path | str,
    *,
    input_arg: str = "",
    mode: str = "auto",  # "auto" | "fact"
    fact_text: str | None = None,
    confidence: str | None = None,
    fact_title: str | None = None,
) -> FeedResult:
    vault_dir = Path(vault_dir)

    if mode == "fact":
        # Codex round 1 Finding 4: fact mode is local-only — no fetch, no
        # profile_check. The user can enter facts even when lark-cli isn't
        # set up at all.
        if not (fact_text and confidence and fact_title):
            raise ValueError(
                "fact mode requires fact_text, confidence, and fact_title"
            )
        from clonemate.feed_parsers.fact import FactParser

        result = FactParser().write_directly(
            vault_dir=vault_dir,
            fact_text=fact_text,
            confidence=confidence,
            title=fact_title,
        )
        return FeedResult(
            parser_name="fact",
            raws_written=0,
            raw_paths=[],
            wiki_path_written=str(
                result.path.relative_to(vault_dir)
            ).replace("\\", "/"),
            was_idempotent_no_op=(not result.created and not result.conflicts),
        )

    # Codex round 2 Finding I: reject empty input_arg in auto mode early.
    # Without this guard, _detect_input("") returns FeedInput with empty
    # body_bytes; TextParser accepts it; we'd write an empty raw — not useful.
    if not input_arg:
        raise ValueError(
            "feed in 'auto' mode requires non-empty input_arg "
            "(file path / URL / '-' for stdin / inline text). "
            "For direct fact entry, use mode='fact' with "
            "fact_text/title/confidence."
        )

    # Non-fact mode: profile_check required (we'll fetch from lark-cli for
    # URL parsers; even local parsers like text don't need it strictly, but
    # we keep the check uniform so the user's vault profile lock is always
    # honored. fact mode is the only exception.)
    profile_check.verify_profile(vault_dir)

    parser = feed_parsers.dispatch(input_arg)
    if parser is None:
        # Codex round 3 Finding H: distinguish "parser-not-found" from
        # "parser-exists-but-extras-missing". The dispatch helper now
        # surfaces the latter via ParserUnavailable so the CLI can print
        # `pip install clonemate[<extra>]` rather than a generic message.
        unavailable = feed_parsers.detect_unavailable_parser(input_arg)
        if unavailable is not None:
            raise ParserUnavailable(
                f"input {input_arg!r} matches the "
                f"{unavailable.expected_parser_name!r} parser, but its "
                f"dependency {unavailable.missing_module!r} is not "
                f"installed. Run `pip install "
                f"clonemate[{unavailable.extras_hint}]` "
                f"or `pip install clonemate[all]`."
            )
        raise NoParserError(
            f"no parser can handle {input_arg!r}. "
            f"Supported: text/md/txt files, lark URLs, pdf/docx/pptx/html "
            f"(extras), --fact mode for direct fact entry."
        )
    fi = feed_parsers._detect_input(input_arg)
    # Codex round 1 Finding 8: pass profile= for parsers that need lark-cli.
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    profile = cy.get("profile", "claude-code")
    raws = parser.parse_with_profile(fi, profile=profile)
    writer = RawWriter(vault_dir)
    written: list[str] = []
    for r in raws:
        wr = writer.write(r)
        if wr.written:
            # Use the actual on-disk relative path (RawWriter rewrites the
            # filename to <stem>-<hash>.md). r.relative_path is the pre-rewrite
            # input path; wr.path is the post-rewrite final path.
            written.append(str(wr.path.relative_to(vault_dir / "raw")))
    return FeedResult(
        parser_name=parser.name,
        raws_written=len(written),
        raw_paths=written,
    )


_INGEST_PROMPT_TEMPLATE = """\
# CloneMate feed — incremental ingest

You are Claude main conversation, invoked by `clonemate feed`. The user just
fed external content into the vault:

  vault: {vault_dir}
  parser: {parser_name}
  raw files written: {raws_written}

Newly written raw paths:
{raw_section}

## Your job

Run **incremental ingest** on these new raws (NOT a full re-ingest):

1. Read each new raw file under `{vault_dir}/raw/...`.
2. For each, decide which wiki page(s) should reflect the new material.
3. Use `merge_note.write(...)` to merge — it's idempotent and conflict-aware.
4. After processing, run:

   python -m clonemate feed-finish --root {root} --slug {slug} --written <N>

   `<N>` is the number of wiki pages you actually wrote. If you decided
   the new raw didn't warrant any wiki update (e.g. content was duplicate,
   irrelevant, or M5 byte-equal idempotency turned it into a no-op),
   pass `--written 0`. The log will record the feed run was driven but
   no wiki landed.

## Don't

- Don't re-ingest the entire vault — only the new raws.
- Don't write to `wiki/voice.md` (M3 voice red line).
- Honor M5 byte-equal idempotency; don't introduce CONFLICT markers when content
  is unchanged.

See `references/prompt-feed.md` for full rubric.
"""


def emit_prompt_for_ingest(
    vault_dir: Path | str, *, result: FeedResult
) -> str:
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    raw_section = "\n".join(f"- `raw/{p}`" for p in result.raw_paths) or "(none)"
    return _INGEST_PROMPT_TEMPLATE.format(
        vault_dir=vault_dir,
        root=vault_dir.parent,
        slug=cy["slug"],
        parser_name=result.parser_name,
        raws_written=result.raws_written,
        raw_section=raw_section,
    )


def feed_finish(vault_dir: Path | str, *, written: int) -> None:
    """After Claude finishes incremental ingest. Logs + auto-commits.

    Codex round 1 Finding 3: spec §6.5 forget Level 2 has hard preflight.
    feed is structurally less risky (raw is .gitignored, no history scrub,
    Claude's wiki writes go through merge_note which has its own M3-M5
    invariants), so we accept `--written` as user-supplied without
    cross-checking. The metric is best-effort — if a user lies about
    `--written`, the worst outcome is a misleading log entry.
    """
    from clonemate import git_ops, index_upsert, log_append

    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    log = vault_dir / "log.md"
    index_upsert.rebuild(vault_dir, display_name=cy["display_name"], log_path=log)
    log_append.append(
        log,
        op="feed",
        subject=cy["slug"],
        metric=f"+{written} raw / wiki updates",
    )
    git_ops._auto_commit_vault(
        vault_dir, message=f"feed: +{written} raw / wiki updates"
    )
