"""Tests for adapters.doc_comments (M2 alignment with real lark-cli surface).

Real CLI: `lark-cli drive file.comments list --params '{"file_token":"<tok>",
"file_type":"docx"}'` → `{"data": {"items": [...]}}`. Each comment carries
`{comment_id, user_id, create_time, reply_list: {replies: [{user_id, content:
{elements: [{type: "text_run", text_run: {text: "..."}}]}}]}}`.
Adapter keeps only comments authored by target.
"""
from __future__ import annotations

import datetime as _dt
import json

from clonemate import lark_cli
from clonemate.adapters import doc_comments
from clonemate.adapters._base import FetchContext


def _ctx(doc_entries=None) -> FetchContext:
    return FetchContext(
        open_id="ou_xxxxxxxxxxxxxxxx",
        my_open_id="ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
        since=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        profile="claude-code",
        quota={"per_source_max_messages": 1000},
        cursor={
            "doc_entries_to_scan": doc_entries or [],
            "doc_to_comment_id": {},
            "status": "pending",
        },
    )


def test_pulls_comments_per_doc(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_run(args, **kw):
        # Real CLI: `drive file.comments list --params '<json>'`
        assert args[:3] == ["drive", "file.comments", "list"]
        params_idx = args.index("--params") + 1
        captured.append(json.loads(args[params_idx]))
        return {"data": {"items": [
            {
                "comment_id": "c1",
                "user_id": "ou_xxxxxxxxxxxxxxxx",
                "create_time": "2026-04-10T10:00",
                "reply_list": {"replies": [{
                    "user_id": "ou_xxxxxxxxxxxxxxxx",
                    "content": {"elements": [
                        {"type": "text_run", "text_run": {"text": "ta 的评论"}},
                    ]},
                }]},
            },
            {
                "comment_id": "c2",
                "user_id": "ou_xxxxxxxxxxxxxxxx",
                "create_time": "2026-04-11T10:00",
                "reply_list": {"replies": [{
                    "user_id": "ou_xxxxxxxxxxxxxxxx",
                    "content": {"elements": [
                        {"type": "text_run", "text_run": {"text": "another"}},
                    ]},
                }]},
            },
            {
                # Authored by someone else — must be filtered out.
                "comment_id": "c3",
                "user_id": "ou_zzzzzzzzzzzzzzzz",  # sanitize: allow-line test fixture
                "create_time": "2026-04-12T10:00",
                "reply_list": {"replies": [{
                    "user_id": "ou_zzzzzzzzzzzzzzzz",  # sanitize: allow-line test fixture
                    "content": {"elements": [
                        {"type": "text_run", "text_run": {"text": "他人评论"}},
                    ]},
                }]},
            },
        ]}}

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = doc_comments.DocCommentsAdapter().fetch(
        _ctx(doc_entries=[{"token": "doxcnXXXXXXXXXXXX", "doc_type": "docx"}])
    )
    assert captured == [{"file_token": "doxcnXXXXXXXXXXXX", "file_type": "docx"}]
    assert len(result.raws) == 1
    raw = result.raws[0]
    assert raw.relative_path == "comments/doxcnXXXXXXXXXXXX.md"
    assert raw.source_type == "comments"
    # Only target's comments survive in body.
    assert "ta 的评论" in raw.content
    assert "他人评论" not in raw.content
    fm = raw.frontmatter
    # spec §3 决策 18: each comment carries author_open_id explicitly
    assert len(fm["comments"]) == 2
    assert all(c["author_open_id"] == "ou_xxxxxxxxxxxxxxxx" for c in fm["comments"])
    assert result.next_cursor["doc_to_comment_id"]["doxcnXXXXXXXXXXXX"] == "c2"
    assert result.next_cursor["status"] == "ok"


def test_fetch_skips_when_comments_list_lacks_permission(monkeypatch) -> None:
    def fake_run(args, **kw):
        raise lark_cli.LarkCliError("[403] permission denied for drive file.comments list")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = doc_comments.DocCommentsAdapter().fetch(
        _ctx(doc_entries=[{"token": "doxcnXXXXXXXXXXXX", "doc_type": "docx"}])
    )
    assert result.raws == []
    assert result.skipped_reason and "scope" in result.skipped_reason
    assert result.next_cursor.get("status") == "permission_blocked"
