"""Shared helper to detect permission/scope errors from lark-cli."""
from __future__ import annotations

import re

# Phrase markers — match prose that explicitly says permission/scope.
_PHRASE_MARKERS = ("permission", "denied", "scope", "unauthorized", "forbidden")

# Code markers — match Lark API/HTTP codes only when they appear in code-like
# positions (after "code:" / "code=" / standalone numbers in error message),
# NOT inside log_id strings that happen to contain those digits.
_CODE_RE = re.compile(
    r"\b(?:code[:=]\s*|status[:=]\s*|HTTP\s+|\[)"  # prefix: code:/status:/HTTP /[
    r"(401|403|41003|41050)\b",
    re.IGNORECASE,
)


def is_permission_error(msg: str) -> bool:
    low = msg.lower()
    if any(m in low for m in _PHRASE_MARKERS):
        return True
    return bool(_CODE_RE.search(msg))
