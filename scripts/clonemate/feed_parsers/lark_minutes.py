"""Feishu minutes URL parser. Mirrors M2 adapters/minutes.py."""
from __future__ import annotations

import datetime as _dt
import re

from clonemate import lark_cli
from clonemate.feed_parsers._base import FeedInput, _BaseParser
from clonemate.raw_writer import RawCandidate

# minute tokens may appear as `mm…`, `mm_…`, or `omm_…` (sanitize_check uses
# the same alternation). Minute URLs look like /minutes/<token>.
_MINUTE_URL_RE = re.compile(
    r"/minutes/(?P<token>(?:omm_|mm_|mm)[A-Za-z0-9]+)"
)


class LarkMinutesParser(_BaseParser):
    name = "lark_minutes"
    extras_hint = None

    def can_handle(self, fi: FeedInput) -> bool:
        return fi.is_url and bool(_MINUTE_URL_RE.search(fi.raw_arg))

    def parse(self, fi: FeedInput) -> list[RawCandidate]:
        raise RuntimeError(
            "lark_minutes parser requires profile; "
            "call parse_with_profile(fi, profile)"
        )

    def parse_with_profile(
        self, fi: FeedInput, profile: str
    ) -> list[RawCandidate]:
        m = _MINUTE_URL_RE.search(fi.raw_arg)
        if not m:
            return []
        token = m.group("token")
        result = lark_cli.run(
            ["minutes", "+fetch", "--minute", token, "--format", "markdown"],
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
                source_type="feed_lark_minutes",
                relative_path=f"feed/lark_minutes/{token}.md",
                hash_input=body,
                frontmatter={
                    "src_type": "feed_lark_minutes",
                    "minute_token": token,
                    "minute_url": fi.raw_arg,
                    "collected_at": now,
                },
                content=body,
            )
        ]
