"""content_hash — stable SHA256 hashing for raw deduplication.

Inputs are normalised (per-line trailing whitespace stripped) before hashing,
so cosmetic whitespace differences don't create new raw files.
"""
from __future__ import annotations

import hashlib


def _normalise(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def compute(text: str) -> str:
    """Return `sha256:<hex>` of normalised text."""
    h = hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()
    return f"sha256:{h}"
