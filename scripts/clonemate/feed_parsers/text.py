"""Text feed parser: handles `.md`, `.txt`, raw inline text, and stdin.

Codex round 1 Finding 11: RawCandidate is imported from
`clonemate.raw_writer` and uses fields (source_type, relative_path,
hash_input, frontmatter, content). The `src_id` is assigned by RawWriter
based on `hash_input` content_hash + content; we don't pre-assign it.
"""
from __future__ import annotations

import datetime as _dt

from clonemate.feed_parsers._base import FeedInput, _BaseParser
from clonemate.raw_writer import RawCandidate


class TextParser(_BaseParser):
    name = "text"
    extras_hint = None

    def can_handle(self, fi: FeedInput) -> bool:
        if fi.is_url:
            return False
        if fi.is_stdin:
            return True
        if fi.path and fi.path.suffix.lower() in {".md", ".txt", ""}:
            return True
        if fi.body_bytes is not None:
            return True
        return False

    def parse(self, fi: FeedInput) -> list[RawCandidate]:
        if fi.is_stdin:
            body = (fi.body_bytes or b"").decode("utf-8")
            src = "stdin"
        elif fi.path:
            body = fi.path.read_text(encoding="utf-8")
            src = fi.path.name
        else:
            body = (fi.body_bytes or b"").decode("utf-8")
            src = "raw-text"
        now = (
            _dt.datetime.now(tz=_dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        return [
            RawCandidate(
                source_type="feed_text",
                relative_path=f"feed/{src}-{now}.md",  # RawWriter dedups via hash_input
                hash_input=body,
                frontmatter={
                    "src_type": "feed_text",
                    "src_origin": src,
                    "collected_at": now,
                },
                content=body,
            )
        ]
