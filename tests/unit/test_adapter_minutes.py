"""Tests for adapters.minutes (M2 alignment with real lark-cli surface).

Real CLI: `lark-cli minutes +search --owner-ids <ou_xxx> --start <YYYY-MM-DD>
--page-size 30 [--page-token <tok>]` → `{"data": {"items": [...], "has_more":
bool, "page_token": str}}`. Adapter calls TWICE — once with `--owner-ids` and
once with `--participant-ids` — then dedupes by minute token. Each item:
`{token, display_info, meta_data: {app_link, description, avatar}}`.
"""
from __future__ import annotations

import datetime as _dt

from clonemate import lark_cli
from clonemate.adapters import minutes
from clonemate.adapters._base import FetchContext

# Use uniform-X placeholder shape to satisfy sanitize_check (mmXXXXXXXXXXXX vs
# mmxxxxxxxxxxxx — case differs so they're distinct paths but both placeholders).
TOKEN_OWNER = "mmXXXXXXXXXXXX"
TOKEN_PART = "mmxxxxxxxxxxxx"


def _ctx() -> FetchContext:
    return FetchContext(
        open_id="ou_xxxxxxxxxxxxxxxx",
        my_open_id="ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
        since=_dt.datetime(2026, 4, 1, tzinfo=_dt.timezone.utc),
        profile="claude-code",
        quota={"per_source_max_messages": 1000},
        cursor={},
    )


def test_merges_owner_and_participant_minutes(monkeypatch) -> None:
    """Adapter calls minutes +search twice (--owner-ids then --participant-ids)
    and dedupes by minute token. Both flags marked correctly in frontmatter."""
    role_calls: list[str] = []

    def fake_run(args, **kw):
        assert args[:2] == ["minutes", "+search"]
        if "--owner-ids" in args:
            role_calls.append("owner")
            assert args[args.index("--owner-ids") + 1] == "ou_xxxxxxxxxxxxxxxx"
            return {"data": {
                "items": [{
                    "token": TOKEN_OWNER,
                    "display_info": "owned 妙记\n所有者: 张三 开始时间: 2026-04-10 时长: 30min",
                    "meta_data": {
                        "app_link": f"https://example.com/minutes/{TOKEN_OWNER}",
                        "description": "owned 描述",
                    },
                }],
                "has_more": False,
                "page_token": "",
            }}
        if "--participant-ids" in args:
            role_calls.append("participant")
            assert args[args.index("--participant-ids") + 1] == "ou_xxxxxxxxxxxxxxxx"
            # Same minute as owner search → must be deduped.
            return {"data": {
                "items": [
                    {
                        "token": TOKEN_OWNER,
                        "display_info": "owned 妙记 (dup)",
                        "meta_data": {
                            "app_link": f"https://example.com/minutes/{TOKEN_OWNER}",
                            "description": "owned dup",
                        },
                    },
                    {
                        "token": TOKEN_PART,
                        "display_info": "joined 妙记\n所有者: 李四 开始时间: 2026-04-12 时长: 10min",
                        "meta_data": {
                            "app_link": f"https://example.com/minutes/{TOKEN_PART}",
                            "description": "joined 描述",
                        },
                    },
                ],
                "has_more": False,
                "page_token": "",
            }}
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = minutes.MinutesAdapter().fetch(_ctx())
    assert role_calls == ["owner", "participant"]

    paths = sorted(r.relative_path for r in result.raws)
    assert paths == sorted([f"minutes/{TOKEN_OWNER}.md", f"minutes/{TOKEN_PART}.md"])

    raw_owner = next(r for r in result.raws if TOKEN_OWNER in r.relative_path)
    assert raw_owner.source_type == "minutes"
    assert raw_owner.frontmatter["author_open_id"] == "ou_xxxxxxxxxxxxxxxx"
    assert raw_owner.frontmatter["minute_token"] == TOKEN_OWNER
    assert raw_owner.frontmatter["url"] == f"https://example.com/minutes/{TOKEN_OWNER}"
    assert raw_owner.frontmatter["is_owner"] is True
    # Title pulled from first line of display_info.
    assert raw_owner.frontmatter["title"] == "owned 妙记"
    assert "owned 妙记" in raw_owner.content

    raw_part = next(r for r in result.raws if TOKEN_PART in r.relative_path)
    assert raw_part.frontmatter["is_owner"] is False
    assert raw_part.frontmatter["is_participant"] is True
    assert result.next_cursor["status"] == "ok"


def test_fetch_skips_when_minutes_search_lacks_permission(monkeypatch) -> None:
    def fake_run(args, **kw):
        raise lark_cli.LarkCliError("[403] permission denied for minutes +search")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = minutes.MinutesAdapter().fetch(_ctx())
    assert result.raws == []
    assert result.skipped_reason and "scope" in result.skipped_reason
    assert result.next_cursor.get("status") == "permission_blocked"
