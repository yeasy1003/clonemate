"""Tests for adapters.im_1v1 (M2 alignment with real lark-cli surface).

Real CLI: `lark-cli im +chat-messages-list --user-id <ou_target> --start <iso>
--end <iso> --page-size 50 --sort asc [--page-token <tok>]` → `{"data":
{"messages": [...], "has_more": bool, "page_token": str}}`. Each message:
`{message_id, msg_type, content, create_time, sender: {id, name}}`. The CLI
returns `create_time` as `"YYYY-MM-DD HH:MM"` (no seconds, no timezone).
Adapter partitions by year-month and writes raws under
`im_1v1/<target_open_id>/<ym>.md`.
"""
from __future__ import annotations

import datetime as _dt

from clonemate import lark_cli
from clonemate.adapters import im_1v1
from clonemate.adapters._base import FetchContext


def _ctx(cursor: dict | None = None) -> FetchContext:
    return FetchContext(
        open_id="ou_xxxxxxxxxxxxxxxx",
        my_open_id="ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
        since=_dt.datetime(2026, 4, 1, tzinfo=_dt.timezone.utc),
        profile="claude-code",
        quota={"per_source_max_messages": 1000},
        cursor=cursor or {},
    )


def test_fetch_groups_messages_by_month_and_advances_cursor(monkeypatch) -> None:
    def fake_run(args, **kw):
        # Real CLI: `im +chat-messages-list --user-id <ou_target> ...`
        assert args[:2] == ["im", "+chat-messages-list"]
        assert "--user-id" in args
        assert args[args.index("--user-id") + 1] == "ou_xxxxxxxxxxxxxxxx"
        return {"data": {
            "messages": [
                {
                    "message_id": "om_aaaaaaaaaaaaaaaa",  # sanitize: allow-line test fixture
                    "msg_type": "text",
                    "content": "你好",
                    "create_time": "2026-04-15 10:01",
                    "sender": {"id": "ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
                               "name": "我"},
                },
                {
                    "message_id": "om_bbbbbbbbbbbbbbbb",  # sanitize: allow-line test fixture
                    "msg_type": "text",
                    "content": "嗯",
                    "create_time": "2026-04-15 10:02",
                    "sender": {"id": "ou_xxxxxxxxxxxxxxxx", "name": "ta"},
                },
                {
                    "message_id": "om_zzzzzzzzzzzzzzzz",  # sanitize: allow-line test fixture
                    "msg_type": "text",
                    "content": "新月",
                    "create_time": "2026-05-02 09:00",
                    "sender": {"id": "ou_xxxxxxxxxxxxxxxx", "name": "ta"},
                },
            ],
            "has_more": False,
            "page_token": "",
        }}

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = im_1v1.Im1v1Adapter().fetch(_ctx())
    paths = sorted(r.relative_path for r in result.raws)
    assert paths == [
        "im_1v1/ou_xxxxxxxxxxxxxxxx/2026-04.md",
        "im_1v1/ou_xxxxxxxxxxxxxxxx/2026-05.md",
    ]

    april = next(r for r in result.raws if r.relative_path.endswith("2026-04.md"))
    assert april.source_type == "im_1v1"
    assert "你好" in april.content
    fm = april.frontmatter
    assert fm["participants"] == ["ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
                                   "ou_xxxxxxxxxxxxxxxx"]
    assert {m["author_open_id"] for m in fm["messages"]} == {
        "ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
        "ou_xxxxxxxxxxxxxxxx",
    }
    # Cursor records the LAST message_id seen (across all pages).
    assert result.next_cursor["chat_to_msg"]["ou_xxxxxxxxxxxxxxxx"] == \
        "om_zzzzzzzzzzzzzzzz"  # sanitize: allow-line test fixture
    assert result.next_cursor["status"] == "ok"


def test_fetch_skips_when_messages_list_lacks_permission(monkeypatch) -> None:
    def fake_run(args, **kw):
        raise lark_cli.LarkCliError("[403] permission denied for im +chat-messages-list")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = im_1v1.Im1v1Adapter().fetch(_ctx())
    assert result.raws == []
    assert result.skipped_reason and "scope" in result.skipped_reason
    assert result.next_cursor.get("status") == "permission_blocked"
