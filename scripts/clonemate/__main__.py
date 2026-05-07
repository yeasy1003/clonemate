# scripts/clonemate/__main__.py
"""clonemate CLI — `python -m clonemate <subcommand>`.

M2 only ships `clone`. Other subcommands (sync / feed / ask / lint / forget /
list / rename / review / undo / migrate) land in later milestones.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clonemate.clone_cmd import clone


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clonemate")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("clone", help="Initialize a new clonemate vault and run first-time auto-collection")
    pc.add_argument("handle", help="colleague handle (Chinese name / email / open_id)")
    pc.add_argument("--root", required=True, help="vault root, e.g. ~/files/clonemate")
    pc.add_argument("--my-open-id", required=True, help="your own open_id (for im_group co-member filter)")
    pc.add_argument("--profile", default="claude-code", help="lark-cli profile")
    pc.add_argument("--since", default="180d", help="time window: 180d / 1y / 2y / YYYY-MM-DD")
    pc.add_argument(
        "--slug",
        default=None,
        help="explicit ASCII slug (required when display_name and email are non-ASCII)",
    )

    pi = sub.add_parser(
        "ingest",
        help="Emit the ingest orchestration prompt for Claude main conversation",
    )
    pi.add_argument("--root", required=True)
    pi.add_argument("--slug", required=True)

    pif = sub.add_parser(
        "ingest-finish",
        help="Run after subagents finish writing wiki: rebuild index + append log",
    )
    pif.add_argument("--root", required=True)
    pif.add_argument("--slug", required=True)
    pif.add_argument("--raw-count", type=int, required=True)
    pif.add_argument("--wiki-count", type=int, required=True)

    pr = sub.add_parser("review", help="Phase B/C — emit review checklist + dialogue prompt")
    pr.add_argument("--root", required=True)
    pr.add_argument("--slug", required=True)

    prf = sub.add_parser("review-finish", help="After Phase C dialogue: rebuild index + log")
    prf.add_argument("--root", required=True)
    prf.add_argument("--slug", required=True)
    prf.add_argument("--resolved", type=int, required=True)
    prf.add_argument("--skipped", type=int, required=True)

    pa = sub.add_parser(
        "ask",
        help="Ask a question of the cloned colleague (Phase ask: voice-transferred answer)",
    )
    pa.add_argument("--root", required=True)
    pa.add_argument("--slug", required=True)
    pa.add_argument("--question", required=True)
    pa.add_argument(
        "--my-open-id", required=True,
        help="your own open_id (used by background sync after ask)",
    )
    pa.add_argument(
        "--no-bg-sync", action="store_true", default=False,
        help="skip the post-ask background incremental sync "
             "(default: bg-sync runs after every ask in default mode)",
    )
    pa_mode = pa.add_mutually_exclusive_group()
    pa_mode.add_argument(
        "--literal",
        action="store_true",
        help="skip voice transfer; output a neutral factual summary",
    )
    pa_mode.add_argument(
        "--voice-only",
        dest="voice_only",
        action="store_true",
        help="prioritize style fidelity over fact completeness (rare)",
    )

    paf = sub.add_parser(
        "ask-finish",
        help="After Phase ask: append log + rebuild index iff synthesis was written + auto-commit",
    )
    paf.add_argument("--root", required=True)
    paf.add_argument("--slug", required=True)
    paf.add_argument("--question", required=True)
    paf.add_argument(
        "--synthesis-written",
        dest="synthesis_written",
        type=int,
        choices=[0, 1],
        required=True,
    )
    paf.add_argument(
        "--synthesis-title",
        dest="synthesis_title",
        default=None,
    )

    pl = sub.add_parser(
        "lint",
        help="Phase lint — emit static report + dynamic-scan prompt",
    )
    pl.add_argument("--root", required=True)
    pl.add_argument("--slug", required=True)

    plf = sub.add_parser(
        "lint-finish",
        help="After Phase lint dialogue: log run + auto-commit",
    )
    plf.add_argument("--root", required=True)
    plf.add_argument("--slug", required=True)
    plf.add_argument("--findings", type=int, required=True)

    pf = sub.add_parser(
        "forget",
        help="Real-delete a vault or single source (spec §6.5)",
    )
    pf.add_argument("--root", required=True)
    pf.add_argument("--slug", required=True)
    pf_grp = pf.add_mutually_exclusive_group()
    pf_grp.add_argument("--source", help="single-source forget (Level 2)")
    pf_grp.add_argument(
        "--hard",
        action="store_true",
        help="full-history scrub (Level 3 — needs --yes-i-mean-it)",
    )
    pf.add_argument(
        "--yes",
        action="store_true",
        help="confirmation for Level 1 (entire vault)",
    )
    pf.add_argument(
        "--yes-i-mean-it",
        dest="yes_i_mean_it",
        action="store_true",
        help="confirmation for Level 3 (vault rm with strong gate)",
    )

    pff = sub.add_parser(
        "forget-finish",
        help="After Phase forget Level 2 dialogue: filter-repo + index + log",
    )
    pff.add_argument("--root", required=True)
    pff.add_argument("--slug", required=True)
    pff.add_argument("--source", required=True)

    psy = sub.add_parser("sync", help="Incremental fetch (spec §6.6)")
    psy.add_argument("--root", required=True)
    psy.add_argument("--slug", required=True)
    psy.add_argument("--my-open-id", required=True)
    psy_grp = psy.add_mutually_exclusive_group()
    psy_grp.add_argument("--source", dest="source_filter", default=None)
    psy_grp.add_argument(
        "--retry-failed",
        dest="retry_failed",
        action="store_true",
    )
    psy.add_argument("--since", default=None)

    psyf = sub.add_parser(
        "sync-finish",
        help="After sync: log + auto-commit (CLI handles in one go usually)",
    )
    psyf.add_argument("--root", required=True)
    psyf.add_argument("--slug", required=True)
    # The CLI tracks the FetchReport in-memory; sync-finish is mostly a no-op
    # path for explicit re-runs. We accept --written/--failed ints to support
    # external-tool-driven workflows.
    psyf.add_argument("--written", type=int, default=0)
    psyf.add_argument("--failed", type=int, default=0)

    pfd = sub.add_parser(
        "feed",
        help=(
            "Ingest external content (spec §6.2). Exit codes: 0=ok, "
            "3=parser dependency missing (run pip install clonemate[<extra>]), "
            "4=no parser matched the input."
        ),
        description=(
            "Ingest external content into the vault (spec §6.2). "
            "Exit codes: 0=ok, "
            "3=parser dependency missing "
            "(run `pip install clonemate[<extra>]`), "
            "4=no parser matched the input."
        ),
    )
    pfd.add_argument("--root", required=True)
    pfd.add_argument("--slug", required=True)
    pfd.add_argument(
        "--input",
        default="",
        help="path / URL / '-' (stdin) / inline text; ignored for --fact",
    )
    pfd_grp = pfd.add_mutually_exclusive_group()
    pfd_grp.add_argument(
        "--fact",
        dest="fact_text",
        help="direct fact entry; bypasses LLM ingest",
    )
    pfd.add_argument(
        "--confidence",
        choices=["high", "medium", "low"],
        default=None,
    )
    pfd.add_argument("--title", dest="fact_title", default=None)

    pfdf = sub.add_parser(
        "feed-finish",
        help="After Claude incremental ingest",
    )
    pfdf.add_argument("--root", required=True)
    pfdf.add_argument("--slug", required=True)
    pfdf.add_argument("--written", type=int, required=True)

    prb = sub.add_parser(
        "rebind",
        help="Re-bind vault to new lark-cli profile",
    )
    prb.add_argument("--root", required=True)
    prb.add_argument("--slug", required=True)
    prb.add_argument("--profile", dest="new_profile", required=True)

    pun = sub.add_parser(
        "undo",
        help="git revert HEAD + index rebuild",
    )
    pun.add_argument("--root", required=True)
    pun.add_argument("--slug", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.cmd == "clone":
        report = clone(
            root=Path(args.root),
            handle=args.handle,
            my_open_id=args.my_open_id,
            profile=args.profile,
            since=args.since,
            slug=args.slug,
        )
        for name, sr in sorted(report.per_source.items()):
            status = "FAIL" if sr.failed else ("SKIP" if sr.skipped_reason else "OK")
            extra = f" — {sr.error or sr.skipped_reason}" if (sr.failed or sr.skipped_reason) else ""
            print(f"  [{status}] {name}: written={sr.written} skipped={sr.skipped}{extra}")
        return 0

    if args.cmd == "ingest":
        from clonemate import ingest_cmd

        vault_dir = Path(args.root) / args.slug
        print(ingest_cmd.emit_prompt(vault_dir))
        return 0

    if args.cmd == "ingest-finish":
        from clonemate import ingest_cmd

        vault_dir = Path(args.root) / args.slug
        ingest_cmd.finish(vault_dir, raw_count=args.raw_count, wiki_count=args.wiki_count)
        print(f"OK: index rebuilt and log appended at {vault_dir}")
        return 0

    if args.cmd == "review":
        from clonemate import review_cmd

        vault_dir = Path(args.root) / args.slug
        print(review_cmd.emit_prompt(vault_dir))
        return 0

    if args.cmd == "review-finish":
        from clonemate import review_cmd

        vault_dir = Path(args.root) / args.slug
        review_cmd.finish(vault_dir, resolved=args.resolved, skipped=args.skipped)
        print(f"OK: review finalised at {vault_dir}")
        return 0

    if args.cmd == "ask":
        from clonemate import query_cmd

        if args.literal:
            mode = "literal"
        elif args.voice_only:
            mode = "voice-only"
        else:
            mode = "default"
        vault_dir = Path(args.root) / args.slug
        print(query_cmd.emit_prompt(vault_dir, args.question, mode=mode))
        # Fire-and-forget incremental sync for the NEXT ask (M5 freshness, T3).
        # Skip in fast modes (literal / voice-only) or when explicitly disabled.
        if not args.no_bg_sync and mode == "default":
            try:
                query_cmd.spawn_background_sync(
                    vault_dir, my_open_id=args.my_open_id,
                )
            except Exception as exc:  # noqa: BLE001 — bg sync must NEVER block ask UX
                # Print to stderr so it doesn't pollute the orchestration prompt on stdout.
                print(f"[bg-sync] skipped: {exc}", file=sys.stderr)
        return 0

    if args.cmd == "ask-finish":
        from clonemate import query_cmd

        synthesis_written = bool(args.synthesis_written)
        if synthesis_written and not args.synthesis_title:
            parser.error(
                "--synthesis-title is required when --synthesis-written 1"
            )
        vault_dir = Path(args.root) / args.slug
        query_cmd.finish(
            vault_dir,
            question=args.question,
            synthesis_written=synthesis_written,
            synthesis_title=args.synthesis_title,
        )
        print(f"OK: query finalised at {vault_dir}")
        return 0

    if args.cmd == "lint":
        from clonemate import lint_cmd

        vault_dir = Path(args.root) / args.slug
        print(lint_cmd.emit_prompt(vault_dir))
        return 0

    if args.cmd == "lint-finish":
        from clonemate import lint_cmd

        vault_dir = Path(args.root) / args.slug
        lint_cmd.finish(vault_dir, findings=args.findings)
        print(f"OK: lint finalised at {vault_dir}")
        return 0

    if args.cmd == "forget":
        from clonemate import forget_cmd

        if args.hard:
            if args.source:
                parser.error("--hard cannot be combined with --source")
            if args.yes:
                parser.error("--hard uses --yes-i-mean-it (not --yes)")
            if not args.yes_i_mean_it:
                parser.error("--hard requires --yes-i-mean-it")
            forget_cmd.forget_level3_hard(
                Path(args.root), args.slug, yes_i_mean_it=True,
            )
            print(f"OK: forget Level 3 (strong-gated rm) on {args.slug}")
            return 0
        if args.source:
            # Codex round 3 Issue-K: --source + --yes makes no sense; --yes
            # is for Level 1 (whole vault). Level 2 has its own gating via
            # the start/finish flow. Reject the combo explicitly.
            if args.yes:
                parser.error(
                    "--source (Level 2) does not use --yes; --yes is only "
                    "for Level 1 (whole-vault forget without --source)."
                )
            if args.yes_i_mean_it:
                parser.error(
                    "--yes-i-mean-it is for --hard, not --source"
                )
            vault_dir = Path(args.root) / args.slug
            try:
                print(forget_cmd.forget_level2_start(vault_dir, source=args.source))
            except forget_cmd.VoiceReferencesForgottenSourceError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 5
            except FileNotFoundError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 6
            return 0
        # Level 1 — entire vault
        if not args.yes:
            parser.error("forget Level 1 requires --yes")
        if args.yes_i_mean_it:
            parser.error("--yes-i-mean-it is for --hard, not Level 1")
        try:
            forget_cmd.forget_level1(Path(args.root), args.slug, yes=True)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 6
        print(f"OK: forget Level 1 on {args.slug}")
        return 0

    if args.cmd == "forget-finish":
        from clonemate import forget_cmd

        vault_dir = Path(args.root) / args.slug
        try:
            forget_cmd.forget_level2_finish(vault_dir, source=args.source)
        except forget_cmd.ForgetStateMissingError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 7
        except forget_cmd.ForgetIncompleteError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 8
        print("OK: forget Level 2 finished — history rewritten")
        return 0

    if args.cmd == "sync":
        from clonemate import sync_cmd

        vault_dir = Path(args.root) / args.slug
        rep = sync_cmd.sync(
            vault_dir,
            my_open_id=args.my_open_id,
            source_filter=args.source_filter,
            retry_failed=args.retry_failed,
            since=args.since,
        )
        sync_cmd.finish(vault_dir, report=rep)
        for name, sr in sorted(rep.per_source.items()):
            status = "FAIL" if sr.failed else (
                "SKIP" if sr.skipped_reason else "OK"
            )
            print(
                f"  [{status}] {name}: written={sr.written} skipped={sr.skipped}"
            )
        return 0

    if args.cmd == "sync-finish":
        from clonemate import sync_cmd
        from clonemate.fetch_sources import FetchReport, SourceReport

        vault_dir = Path(args.root) / args.slug
        # External-tool-driven workflows pass --written/--failed ints; build a
        # synthetic FetchReport so finish() can write a uniform log line.
        rep = FetchReport()
        if args.failed:
            rep.per_source["external"] = SourceReport(
                name="external",
                written=args.written,
                failed=True,
                error=f"{args.failed} source(s) failed",
            )
        else:
            rep.per_source["external"] = SourceReport(
                name="external", written=args.written,
            )
        sync_cmd.finish(vault_dir, report=rep)
        print(f"OK: sync finalised at {vault_dir}")
        return 0

    if args.cmd == "feed":
        from clonemate import feed_cmd

        vault_dir = Path(args.root) / args.slug
        if args.fact_text:
            if not args.confidence or not args.fact_title:
                parser.error("--fact requires --confidence and --title")
            result = feed_cmd.feed(
                vault_dir,
                mode="fact",
                fact_text=args.fact_text,
                confidence=args.confidence,
                fact_title=args.fact_title,
            )
            # Codex round 1 Finding 12: surface idempotency outcome.
            if result.was_idempotent_no_op:
                print(
                    f"OK: fact already exists at "
                    f"wiki/syntheses/{args.fact_title}.md (no changes)"
                )
            else:
                print(
                    f"OK: fact written to "
                    f"wiki/syntheses/{args.fact_title}.md"
                )
            return 0
        if not args.input:
            parser.error("either --input or --fact required")
        try:
            result = feed_cmd.feed(vault_dir, input_arg=args.input)
        except feed_cmd.ParserUnavailable as exc:
            # Codex round 3 Finding H: extras-install hint to user.
            print(f"ERROR: {exc}", file=sys.stderr)
            return 3
        except feed_cmd.NoParserError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 4
        print(feed_cmd.emit_prompt_for_ingest(vault_dir, result=result))
        return 0

    if args.cmd == "feed-finish":
        from clonemate import feed_cmd

        vault_dir = Path(args.root) / args.slug
        feed_cmd.feed_finish(vault_dir, written=args.written)
        print(f"OK: feed finalised at {vault_dir}")
        return 0

    if args.cmd == "rebind":
        from clonemate import rebind_cmd

        vault_dir = Path(args.root) / args.slug
        rebind_cmd.rebind(vault_dir, new_profile=args.new_profile)
        print(f"OK: rebound {args.slug} to profile {args.new_profile!r}")
        return 0

    if args.cmd == "undo":
        from clonemate import undo_cmd

        vault_dir = Path(args.root) / args.slug
        undo_cmd.undo(vault_dir)
        print(f"OK: undo at {vault_dir}")
        return 0

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
