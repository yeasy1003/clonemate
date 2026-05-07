"""Fact parser: writes a synthesis page directly, bypassing LLM ingest.
Used for `clonemate feed --fact "..." --confidence X` (spec §7.3 last row)."""
from __future__ import annotations

from pathlib import Path

from clonemate import merge_note
from clonemate.feed_parsers._base import FeedInput, _BaseParser


class FactParser(_BaseParser):
    name = "fact"
    extras_hint = None

    def can_handle(self, fi: FeedInput) -> bool:
        # FactParser is invoked explicitly by feed_cmd, not auto-dispatched.
        return False

    def parse(self, fi: FeedInput):
        return []  # not used

    def write_directly(
        self,
        *,
        vault_dir: Path,
        fact_text: str,
        confidence: str,
        title: str,
    ):
        """Write a synthesis page directly via merge_note.write.

        Codex round 1 Finding 12: returns the WriteResult so feed_cmd can
        surface idempotency / conflict outcomes to the user (M5 byte-equal
        idempotency may make a re-feed a no-op; M3 section-merge may emit
        a CONFLICT marker on collision)."""
        body = f"# {title}\n\n## Fact\n{fact_text}\n"
        return merge_note.write(
            vault_dir=vault_dir,
            page_type="synthesis",
            title=title,
            sources=[],
            confidence=confidence,
            body=body,
            author_role="user",
        )
