"""Feishu docx/wiki URL parser. Uses lark_cli.run with the vault's profile.

Codex round 1 Finding 8: lark_cli.run requires profile= kwarg and returns a
dict; mirror M2 adapters/docs_owned.py:43-46.
"""
from __future__ import annotations

import datetime as _dt
import re

from clonemate import lark_cli
from clonemate.feed_parsers._base import FeedInput, _BaseParser
from clonemate.raw_writer import RawCandidate

_DOCX_URL_RE = re.compile(
    r"/(docx|wiki)/(?P<token>(?:doxcn|wikcn|doccn)[A-Za-z0-9]+)"
)


class LarkDocParser(_BaseParser):
    name = "lark_doc"
    extras_hint = None

    def can_handle(self, fi: FeedInput) -> bool:
        return fi.is_url and bool(_DOCX_URL_RE.search(fi.raw_arg))

    def parse(self, fi: FeedInput) -> list[RawCandidate]:
        # Should not be called directly without profile.
        raise RuntimeError(
            "lark_doc parser requires profile; "
            "call parse_with_profile(fi, profile)"
        )

    def parse_with_profile(
        self, fi: FeedInput, profile: str
    ) -> list[RawCandidate]:
        m = _DOCX_URL_RE.search(fi.raw_arg)
        if not m:
            return []
        token = m.group("token")
        result = lark_cli.run(
            ["docs", "+fetch", "--doc", token, "--doc-format", "markdown"],
            profile=profile,
        )
        body = result.get("markdown", "")
        now = (
            _dt.datetime.now(tz=_dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        return [
            RawCandidate(
                source_type="feed_lark_doc",
                relative_path=f"feed/lark_doc/{token}.md",
                hash_input=body,
                frontmatter={
                    "src_type": "feed_lark_doc",
                    "doc_token": token,
                    "doc_url": fi.raw_arg,
                    "collected_at": now,
                },
                content=body,
            )
        ]
