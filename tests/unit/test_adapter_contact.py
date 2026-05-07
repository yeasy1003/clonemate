"""Tests for adapters.contact (M2 alignment with real lark-cli surface)."""
from __future__ import annotations

import datetime as _dt

from clonemate import lark_cli
from clonemate.adapters import contact
from clonemate.adapters._base import FetchContext


def _ctx(open_id: str = "ou_xxxxxxxxxxxxxxxx") -> FetchContext:
    return FetchContext(
        open_id=open_id,
        my_open_id="ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
        since=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        profile="claude-code",
        quota={"per_source_max_messages": 1000},
        cursor={},
    )


def test_fetch_returns_one_profile_candidate(monkeypatch) -> None:
    def fake_run(args, **kw):
        if args[:2] == ["contact", "+get-user"]:
            return {"data": {"user": {
                "name": "张三",
                "user_id": "ou_xxxxxxxxxxxxxxxx",
                "i18n_name": {"en_us": "Zhang San"},
            }}}
        if args[:2] == ["contact", "+search-user"]:
            return {"data": {"users": [{
                "open_id": "ou_xxxxxxxxxxxxxxxx",
                "localized_name": "张三",
                "email": "zhangsan@example.com",
                "department": "Y 团队",
            }]}}
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = contact.ContactAdapter().fetch(_ctx())
    assert len(result.raws) == 1
    raw = result.raws[0]
    assert raw.source_type == "contact"
    assert raw.relative_path == "contact/profile.md"
    assert "张三" in raw.content
    assert "Zhang San" in raw.content
    assert "Y 团队" in raw.content
    assert raw.frontmatter["author_open_id"] == "ou_xxxxxxxxxxxxxxxx"
    assert result.next_cursor.get("status") == "ok"


def test_fetch_skips_when_get_user_lacks_permission(monkeypatch) -> None:
    def fake_run(args, **kw):
        raise lark_cli.LarkCliError("[401] permission denied for contact +get-user")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = contact.ContactAdapter().fetch(_ctx())
    assert result.raws == []
    assert result.skipped_reason and "scope" in result.skipped_reason
    assert result.next_cursor.get("status") == "permission_blocked"
