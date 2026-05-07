"""Feed parser registry. Built-in parsers are imported on demand to avoid
forcing extras at import time."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clonemate.feed_parsers._base import (  # noqa: F401  (re-exported)
    FeedInput,
    FeedParser,
    ParserUnavailable,
    _BaseParser,
)


class StdinIsTtyError(RuntimeError):
    """Codex round 1 Finding 9: stdin '-' was passed but stdin is a TTY
    (no piped content). Prevents pytest hang and gives the user a clear hint."""


def _detect_input(arg: str) -> FeedInput:
    """Normalize a CLI input arg into FeedInput.
    URL-like → is_url; existing file → path; otherwise raw text.

    For arg == "-", reads stdin only if stdin is NOT a TTY; otherwise raises
    StdinIsTtyError (prevents hang on accidental `feed --input -` without pipe).
    """
    if arg == "-":
        import sys

        if sys.stdin.isatty():
            raise StdinIsTtyError(
                "input '-' requires content piped into stdin "
                "(e.g. `cat note.md | clonemate feed --input -`); "
                "stdin is currently a TTY."
            )
        return FeedInput(
            raw_arg=arg,
            is_stdin=True,
            body_bytes=sys.stdin.read().encode("utf-8"),
        )
    if arg.startswith(("http://", "https://")):
        return FeedInput(raw_arg=arg, is_url=True)
    p = Path(arg)
    if p.is_file():
        return FeedInput(raw_arg=arg, path=p)
    # Treat raw text content
    return FeedInput(raw_arg=arg, body_bytes=arg.encode("utf-8"))


def list_parsers() -> list[FeedParser]:
    """Return all available parsers, in dispatch priority order."""
    out: list[FeedParser] = []
    # text first (catches md/txt + raw text)
    from clonemate.feed_parsers.text import TextParser

    out.append(TextParser())
    # URL parsers — order matters (lark URLs before generic html)
    try:
        from clonemate.feed_parsers.lark_doc import LarkDocParser

        out.append(LarkDocParser())
    except ImportError:
        pass
    try:
        from clonemate.feed_parsers.lark_sheet import LarkSheetParser

        out.append(LarkSheetParser())
    except ImportError:
        pass
    try:
        from clonemate.feed_parsers.lark_minutes import LarkMinutesParser

        out.append(LarkMinutesParser())
    except ImportError:
        pass
    # File parsers (extras-gated)
    for mod_name in ("pdf", "docx", "pptx", "html"):
        try:
            mod = __import__(
                f"clonemate.feed_parsers.{mod_name}", fromlist=["Parser"]
            )
            out.append(mod.Parser())
        except ImportError:
            # Extras not installed — parser unavailable
            pass
    return out


def dispatch(arg: str) -> FeedParser | None:
    """Return the first parser that can_handle() the input, or None."""
    fi = _detect_input(arg)
    for p in list_parsers():
        if p.can_handle(fi):
            return p
    return None


@dataclass
class _UnavailableMatch:
    expected_parser_name: str
    missing_module: str
    extras_hint: str


def detect_unavailable_parser(arg: str) -> _UnavailableMatch | None:
    """Codex round 3 Finding H: when dispatch() returns None, this helper
    decides whether the input WOULD have matched an extras-gated parser if
    the optional dep were installed. Returns details for the CLI to print
    a `pip install clonemate[<extra>]` hint, or None if the input genuinely
    has no matching parser.

    Decision is based on file suffix / URL pattern, NOT on parser registration:
    we DON'T import the extras-gated module (that would defeat the purpose).
    """
    p = (
        Path(arg)
        if not arg.startswith(("http://", "https://")) and arg != "-"
        else None
    )
    suffix = p.suffix.lower() if p else ""
    suffix_map = {
        ".pdf": ("pdf", "pypdf", "pdf"),
        ".docx": ("docx", "docx", "docx"),
        ".pptx": ("pptx", "pptx", "pptx"),
        ".html": ("html", "markdownify", "html"),
        ".htm": ("html", "markdownify", "html"),
    }
    if suffix in suffix_map:
        parser_name, module_name, extras = suffix_map[suffix]
        try:
            __import__(module_name)
            return None  # dep is installed; the parser should have matched
        except ImportError:
            return _UnavailableMatch(parser_name, module_name, extras)
    return None
