"""PDF parser — requires pypdf>=4.0 (`pip install clonemate[pdf]`)."""
from __future__ import annotations

import datetime as _dt
import hashlib

import pypdf  # ImportError → registry skips this parser

from clonemate.feed_parsers._base import FeedInput, _BaseParser
from clonemate.raw_writer import RawCandidate


class Parser(_BaseParser):
    name = "pdf"
    extras_hint = "pdf"

    def can_handle(self, fi: FeedInput) -> bool:
        return fi.path is not None and fi.path.suffix.lower() == ".pdf"

    def parse(self, fi: FeedInput) -> list[RawCandidate]:
        assert fi.path is not None
        reader = pypdf.PdfReader(str(fi.path))
        body = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        now = (
            _dt.datetime.now(tz=_dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        return [
            RawCandidate(
                source_type="feed_pdf",
                relative_path=f"feed/pdf/{fi.path.stem}-{digest}.md",
                hash_input=body,
                frontmatter={
                    "src_type": "feed_pdf",
                    "src_origin": fi.path.name,
                    "collected_at": now,
                },
                content=body,
            )
        ]
