"""adapters/_base.py — Protocol and shared dataclasses for source adapters.

Each adapter gets a `FetchContext` and returns `AdapterResult`. The orchestrator
(`fetch_sources.py`) decides whether to advance cursors, log errors, etc.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Protocol

from clonemate.raw_writer import RawCandidate


@dataclass
class FetchContext:
    open_id: str                    # the colleague being cloned
    my_open_id: str                 # the caller (for im_group "co-member" filter)
    since: _dt.datetime
    profile: str                    # lark-cli profile
    quota: dict[str, int]           # {"per_source_max_messages": 1000, ...}
    cursor: dict[str, Any]          # this source's cursor (may be empty for first run)


@dataclass
class AdapterResult:
    raws: list[RawCandidate]                  # candidates to be written
    next_cursor: dict[str, Any]               # caller advances on success
    skipped_reason: str | None = None         # e.g. "quota exceeded", "api error"


class SourceAdapter(Protocol):
    name: str                       # "contact" / "im_1v1" / etc.

    def fetch(self, ctx: FetchContext) -> AdapterResult:  # pragma: no cover - protocol
        ...
