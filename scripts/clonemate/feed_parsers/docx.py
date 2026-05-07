"""DOCX parser — requires python-docx (`pip install clonemate[docx]`)."""
from __future__ import annotations

import datetime as _dt
import hashlib

import docx  # python-docx; ImportError → registry skips this parser

from clonemate.feed_parsers._base import FeedInput, _BaseParser
from clonemate.raw_writer import RawCandidate


class Parser(_BaseParser):
    name = "docx"
    extras_hint = "docx"

    def can_handle(self, fi: FeedInput) -> bool:
        return fi.path is not None and fi.path.suffix.lower() == ".docx"

    def parse(self, fi: FeedInput) -> list[RawCandidate]:
        assert fi.path is not None
        doc = docx.Document(str(fi.path))
        body = "\n\n".join(p.text for p in doc.paragraphs if p.text)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        now = (
            _dt.datetime.now(tz=_dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        return [
            RawCandidate(
                source_type="feed_docx",
                relative_path=f"feed/docx/{fi.path.stem}-{digest}.md",
                hash_input=body,
                frontmatter={
                    "src_type": "feed_docx",
                    "src_origin": fi.path.name,
                    "collected_at": now,
                },
                content=body,
            )
        ]
