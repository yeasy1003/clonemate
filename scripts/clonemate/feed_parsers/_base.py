"""Base contract for feed parsers (spec §6.2 / §7.3)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ParserUnavailable(RuntimeError):
    """Raised when a parser's optional dep is missing.
    The CLI catches this and prints `pip install clonemate[<extra>]`."""


@dataclass
class FeedInput:
    """Normalized input passed to a parser."""

    raw_arg: str
    path: Path | None = None
    is_url: bool = False
    is_stdin: bool = False
    body_bytes: bytes | None = None


class FeedParser(Protocol):
    name: str
    extras_hint: str | None  # e.g. "pdf" → `pip install clonemate[pdf]`

    def can_handle(self, fi: FeedInput) -> bool: ...

    def parse(self, fi: FeedInput) -> list:
        """Default parse — used by parsers that don't need profile (text/pdf/etc)."""

    def parse_with_profile(self, fi: FeedInput, profile: str) -> list:
        """Lark-* parsers override this. Default delegates to parse()."""


class _BaseParser:
    """Shared base. Codex round 2 Finding B: every concrete parser MUST inherit
    from this so the default `parse_with_profile` is in scope.

    Without inheritance, `feed_cmd.feed()` calling
    `parser.parse_with_profile(...)` raises AttributeError on parsers that
    don't need profile (text / pdf / etc.).
    """

    extras_hint: str | None = None

    def parse_with_profile(self, fi: FeedInput, profile: str):
        return self.parse(fi)
