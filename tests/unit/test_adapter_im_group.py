"""Tests for adapters.im_group (M2 alignment with real lark-cli surface).

Real CLI sequence:
  1. `lark-cli im +chat-search --member-ids <ou> --search-types
     public_joined,private --page-size 100 [--page-token <tok>]`
     → `{"data": {"chats": [...], "has_more": bool, "page_token": str}}`
     Called twice (once for target, once for caller); only chats both share
     are read.
  2. Per shared chat: `lark-cli im +chat-messages-list --chat-id <oc_xxx>
     --start <iso> --end <iso> --page-size 50 --sort asc [--page-token <tok>]`
     → `{"data": {"messages": [...], "has_more": bool, "page_token": str}}`

Signal filter: keep only messages where `sender.id == target_open_id`, plus
±_CONTEXT_WINDOW context. Permission errors on chat-search short-circuit.
Per-chat read failures are recorded but don't fail the whole run.
"""
from __future__ import annotations

import datetime as _dt

from clonemate import lark_cli
from clonemate.adapters import im_group
from clonemate.adapters._base import FetchContext


def _ctx() -> FetchContext:
    return FetchContext(
        open_id="ou_xxxxxxxxxxxxxxxx",
        my_open_id="ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
        since=_dt.datetime(2026, 4, 1, tzinfo=_dt.timezone.utc),
        profile="claude-code",
        quota={"per_source_max_messages": 1000},
        cursor={},
    )


def test_filters_to_self_messages_with_context(monkeypatch) -> None:
    """Per-chat: only messages where sender.id == target are 'signals'.
    Adapter expands ±_CONTEXT_WINDOW around each signal and writes one raw
    per (chat, year-month). chat-search is called for both target and caller;
    only the intersection is read."""
    shared_chat = {"chat_id": "oc_aaaaaaaaaaaaaaaa",  # sanitize: allow-line test fixture
                   "name": "Y 团队"}

    def fake_run(args, **kw):
        if args[:2] == ["im", "+chat-search"]:
            assert "--member-ids" in args
            member = args[args.index("--member-ids") + 1]
            assert member in ("ou_xxxxxxxxxxxxxxxx", "ou_yyyyyyyyyyyyyyyy")  # sanitize: allow-line test fixture  # noqa: E501
            return {"data": {
                "chats": [shared_chat],
                "has_more": False,
                "page_token": "",
            }}
        if args[:2] == ["im", "+chat-messages-list"]:
            assert "--chat-id" in args
            assert args[args.index("--chat-id") + 1] == \
                "oc_aaaaaaaaaaaaaaaa"  # sanitize: allow-line test fixture
            return {"data": {
                "messages": [
                    {
                        "message_id": "om_aaaaaaaaaaaaaaaa",  # sanitize: allow-line test fixture
                        "msg_type": "text",
                        "content": "其他人 0",
                        "create_time": "2026-04-10 09:00",
                        "sender": {"id": "ou_zzzzzzzzzzzzzzzz",  # sanitize: allow-line test fixture
                                   "name": "他人"},
                    },
                    {
                        "message_id": "om_bbbbbbbbbbbbbbbb",  # sanitize: allow-line test fixture
                        "msg_type": "text",
                        "content": "我是 ta 的发言",
                        "create_time": "2026-04-10 09:01",
                        "sender": {"id": "ou_xxxxxxxxxxxxxxxx", "name": "ta"},
                    },
                    {
                        "message_id": "om_cccccccccccccccc",  # sanitize: allow-line test fixture
                        "msg_type": "text",
                        "content": "其他人回复",
                        "create_time": "2026-04-10 09:02",
                        "sender": {"id": "ou_zzzzzzzzzzzzzzzz",  # sanitize: allow-line test fixture
                                   "name": "他人"},
                    },
                ],
                "has_more": False,
                "page_token": "",
            }}
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = im_group.ImGroupAdapter().fetch(_ctx())
    assert len(result.raws) == 1  # one (chat, month) bucket
    raw = result.raws[0]
    assert raw.source_type == "im_group"
    assert raw.relative_path == \
        "im_group/oc_aaaaaaaaaaaaaaaa/2026-04.md"  # sanitize: allow-line test fixture
    fm = raw.frontmatter
    # Within ±20 context, all 3 messages survive.
    assert len(fm["messages"]) == 3
    authors = {m["author_open_id"] for m in fm["messages"]}
    assert "ou_xxxxxxxxxxxxxxxx" in authors
    assert fm["chat_id"] == "oc_aaaaaaaaaaaaaaaa"  # sanitize: allow-line test fixture
    assert fm["chat_name"] == "Y 团队"
    assert "self_message" in fm["filter_reasons"]
    assert result.next_cursor["status"] == "ok"
    assert result.next_cursor["chat_to_msg"][
        "oc_aaaaaaaaaaaaaaaa"  # sanitize: allow-line test fixture
    ] == "om_cccccccccccccccc"  # sanitize: allow-line test fixture


def test_only_reads_chats_shared_with_caller(monkeypatch) -> None:
    """Adapter intersects target's chats with caller's chats and only fetches
    messages from the shared set; chats only target (or only caller) is in
    are skipped without a chat-messages-list call."""
    target_chats = [
        {"chat_id": "oc_aaaaaaaaaaaaaaaa", "name": "target only"},  # sanitize: allow-line test fixture
        {"chat_id": "oc_bbbbbbbbbbbbbbbb", "name": "shared"},  # sanitize: allow-line test fixture
    ]
    my_chats = [
        {"chat_id": "oc_bbbbbbbbbbbbbbbb", "name": "shared"},  # sanitize: allow-line test fixture
        {"chat_id": "oc_cccccccccccccccc", "name": "mine only"},  # sanitize: allow-line test fixture
    ]
    messages_calls: list[str] = []

    def fake_run(args, **kw):
        if args[:2] == ["im", "+chat-search"]:
            member = args[args.index("--member-ids") + 1]
            if member == "ou_xxxxxxxxxxxxxxxx":  # target
                return {"data": {"chats": target_chats, "has_more": False, "page_token": ""}}
            if member == "ou_yyyyyyyyyyyyyyyy":  # sanitize: allow-line test fixture
                return {"data": {"chats": my_chats, "has_more": False, "page_token": ""}}
            raise AssertionError(f"unexpected member: {member}")
        if args[:2] == ["im", "+chat-messages-list"]:
            chat_id = args[args.index("--chat-id") + 1]
            messages_calls.append(chat_id)
            return {"data": {
                "messages": [{
                    "message_id": "om_aaaaaaaaaaaaaaaa",  # sanitize: allow-line test fixture
                    "msg_type": "text",
                    "content": "hi",
                    "create_time": "2026-04-10 09:00",
                    "sender": {"id": "ou_xxxxxxxxxxxxxxxx", "name": "ta"},
                }],
                "has_more": False,
                "page_token": "",
            }}
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = im_group.ImGroupAdapter().fetch(_ctx())
    assert messages_calls == ["oc_bbbbbbbbbbbbbbbb"]  # sanitize: allow-line test fixture
    assert len(result.raws) == 1
    assert result.raws[0].relative_path.startswith(
        "im_group/oc_bbbbbbbbbbbbbbbb/"  # sanitize: allow-line test fixture
    )


def test_fetch_skips_when_chat_search_lacks_permission(monkeypatch) -> None:
    def fake_run(args, **kw):
        raise lark_cli.LarkCliError("[403] permission denied for im +chat-search")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = im_group.ImGroupAdapter().fetch(_ctx())
    assert result.raws == []
    assert result.skipped_reason and "scope" in result.skipped_reason
    assert result.next_cursor.get("status") == "permission_blocked"
