"""Feishu sheet URL parser. Mirrors M2 adapters/docs_owned.py csv path."""
from __future__ import annotations

import datetime as _dt
import re

from clonemate import lark_cli
from clonemate.feed_parsers._base import FeedInput, _BaseParser
from clonemate.raw_writer import RawCandidate

_SHEET_URL_RE = re.compile(r"/sheets/(?P<token>shtcn[A-Za-z0-9]+)")


class LarkSheetParser(_BaseParser):
    name = "lark_sheet"
    extras_hint = None

    def can_handle(self, fi: FeedInput) -> bool:
        return fi.is_url and bool(_SHEET_URL_RE.search(fi.raw_arg))

    def parse(self, fi: FeedInput) -> list[RawCandidate]:
        raise RuntimeError(
            "lark_sheet parser requires profile; "
            "call parse_with_profile(fi, profile)"
        )

    def parse_with_profile(
        self, fi: FeedInput, profile: str
    ) -> list[RawCandidate]:
        m = _SHEET_URL_RE.search(fi.raw_arg)
        if not m:
            return []
        token = m.group("token")
        result = lark_cli.run(
            ["docs", "+export", "--doc", token, "--format", "csv"],
            profile=profile,
        )
        body = result.get("csv", "")
        now = (
            _dt.datetime.now(tz=_dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        return [
            RawCandidate(
                source_type="feed_lark_sheet",
                relative_path=f"feed/lark_sheet/{token}.md",
                hash_input=body,
                frontmatter={
                    "src_type": "feed_lark_sheet",
                    "sheet_token": token,
                    "sheet_url": fi.raw_arg,
                    "collected_at": now,
                },
                content=body,
            )
        ]
