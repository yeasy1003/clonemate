"""plugins — entry-point–based source plugin discovery.

Plugins register under group `clonemate.sources` via pyproject.toml:

    [project.entry-points."clonemate.sources"]
    meego = "my_meego_plugin:MeegoSource"

clonemate.fetch_sources only loads plugins listed in `_clone.yaml.plugins_allowed`
(opt-in white-list — spec §7.4 / §11 risk: malicious plugin).
"""
from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import Any


def _iter_entry_points() -> Iterable[Any]:
    """Wrapped for test injection."""
    return entry_points(group="clonemate.sources")


def discover(*, allowlist: list[str]) -> dict[str, Any]:
    """Discover registered source plugins, filtered by allowlist.

    Returns a {name: loaded_object} mapping. Plugins not in allowlist are skipped.
    """
    allowed = set(allowlist)
    out: dict[str, Any] = {}
    for ep in _iter_entry_points():
        if ep.name not in allowed:
            continue
        out[ep.name] = ep.load()
    return out
