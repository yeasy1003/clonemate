"""resolve — handle (chinese name / email / open_id) → list of (open_id, app_id, display_name) candidates.

Strategy:
1. If handle starts with `ou_`, treat as open_id; query lark-cli auth status to learn the current app_id.
2. If handle contains `@`, treat as email; search via `contact +search-user`.
3. Else treat as a name (Chinese / pinyin); search via `contact +search-user` and return all matches.

Multiple matches are returned as candidates; the caller (clone_cmd) does the disambiguation UX.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from clonemate import lark_cli


class ResolveError(RuntimeError):
    """Raised when no candidate or lookup fails permanently."""


@dataclass
class Candidate:
    open_id: str
    app_id: str
    display_name: str
    email: str | None = None


_OPEN_ID_RE = re.compile(r"^ou_[A-Za-z0-9]{10,}$")


def _current_app_id(profile: str) -> str:
    """Read app_id from `lark-cli auth status` (JSON-by-default, field `appId`)."""
    out = lark_cli.run(["auth", "status"], profile=profile)
    return out["appId"]


def _make_candidate(u: dict, app_id: str) -> Candidate:
    return Candidate(
        open_id=u["open_id"],
        app_id=app_id,
        display_name=u.get("localized_name") or u.get("name") or u["open_id"],
        email=u.get("email") or u.get("enterprise_email"),
    )


def resolve_handle(handle: str, *, profile: str) -> list[Candidate]:
    app_id = _current_app_id(profile)
    if _OPEN_ID_RE.match(handle):
        return [Candidate(open_id=handle, app_id=app_id, display_name=handle)]

    # Email or name search via contact +search-user (user-only command).
    out = lark_cli.run(
        ["contact", "+search-user", "--query", handle, "--as", "user"],
        profile=profile,
    )
    users = (out.get("data") or {}).get("users") or []
    if not users:
        raise ResolveError(f"no match for handle {handle!r}")
    return [_make_candidate(u, app_id) for u in users]
