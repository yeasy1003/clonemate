"""meego — placeholder stub. Real Meego support ships as an external plugin
registered via entry-points group `clonemate.sources` (see clonemate.plugins).

This stub exists so the built-in adapter registry has an entry; fetch_sources
skips it because _clone.yaml.sources_enabled.meego defaults to false.
"""
from __future__ import annotations

from clonemate.adapters._base import AdapterResult, FetchContext


class MeegoStub:
    name: str = "meego"

    def fetch(self, ctx: FetchContext) -> AdapterResult:  # noqa: ARG002
        raise NotImplementedError(
            "meego is not built-in; install a clonemate.sources plugin and add `meego` to plugins_allowed."
        )
