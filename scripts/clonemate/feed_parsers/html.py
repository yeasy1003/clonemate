"""HTML parser — requires markdownify + requests (`pip install clonemate[html]`).

Handles local `.html` / `.htm` files. (Remote URL fetching is intentionally
out of scope for this parser; the lark URL parsers cover Feishu URLs and a
generic web fetcher is a future extension.)
"""
from __future__ import annotations

import datetime as _dt
import hashlib

# requests is currently unused at parse-time (we only handle local files), but
# the extra ships it for future remote-URL support; importing it here keeps
# `pip install clonemate[html]` honest about the install footprint.
import requests  # noqa: F401  (extras footprint anchor; ImportError → skip)
from markdownify import markdownify as _md

from clonemate.feed_parsers._base import FeedInput, _BaseParser
from clonemate.raw_writer import RawCandidate


class Parser(_BaseParser):
    name = "html"
    extras_hint = "html"

    def can_handle(self, fi: FeedInput) -> bool:
        return (
            fi.path is not None
            and fi.path.suffix.lower() in {".html", ".htm"}
        )

    def parse(self, fi: FeedInput) -> list[RawCandidate]:
        assert fi.path is not None
        html_text = fi.path.read_text(encoding="utf-8")
        body = _md(html_text)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        now = (
            _dt.datetime.now(tz=_dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        return [
            RawCandidate(
                source_type="feed_html",
                relative_path=f"feed/html/{fi.path.stem}-{digest}.md",
                hash_input=body,
                frontmatter={
                    "src_type": "feed_html",
                    "src_origin": fi.path.name,
                    "collected_at": now,
                },
                content=body,
            )
        ]
