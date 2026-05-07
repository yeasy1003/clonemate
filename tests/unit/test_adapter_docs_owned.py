"""Tests for adapters.docs_owned (M2 alignment with real lark-cli surface).

Real CLI: `lark-cli drive +search --creator-ids <ou_xxx> --created-since <iso>
--doc-types docx,wiki,sheet --page-size 20 [--page-token <tok>] --query ""`
returns `{"data": {"results": [...], "has_more": bool, "page_token": str}}`.
Each result: `{token, entity_type, result_meta: {token, owner_id, owner_name,
edit_user_id, doc_types, url, create_time_iso, update_time_iso, ...},
title_highlighted, summary_highlighted}`.

Adapter only emits results where `result_meta.owner_id == target.open_id`.
Body is NOT fetched in this adapter — only metadata is stored.
"""
from __future__ import annotations

import datetime as _dt

from clonemate import lark_cli
from clonemate.adapters import docs_owned
from clonemate.adapters._base import FetchContext


def _ctx() -> FetchContext:
    return FetchContext(
        open_id="ou_xxxxxxxxxxxxxxxx",
        my_open_id="ou_yyyyyyyyyyyyyyyy",  # sanitize: allow-line test fixture
        since=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
        profile="claude-code",
        quota={"per_source_max_messages": 1000, "per_source_max_mb": 100},
        cursor={},
    )


def test_emits_metadata_per_owned_doc(monkeypatch) -> None:
    """Adapter calls drive +search, filters to docs owned by target, and writes
    one raw per owned doc carrying token + url + doc_type metadata only."""
    def fake_run(args, **kw):
        assert args[:2] == ["drive", "+search"]
        # Sanity: required flags present
        assert "--creator-ids" in args
        assert args[args.index("--creator-ids") + 1] == "ou_xxxxxxxxxxxxxxxx"
        assert "--doc-types" in args
        return {"data": {
            "results": [
                {
                    "entity_type": "docx",
                    "title_highlighted": "<em>架构</em>方案",
                    "summary_highlighted": "<em>设计</em>说明",
                    "result_meta": {
                        "token": "doxcnXXXXXXXXXXXX",
                        "owner_id": "ou_xxxxxxxxxxxxxxxx",
                        "owner_name": "张三",
                        "doc_types": "docx",
                        "url": "https://example.com/docx/aaa",
                        "create_time_iso": "2026-04-15T10:00:00+08:00",
                        "update_time_iso": "2026-04-20T10:00:00+08:00",
                    },
                },
                {
                    # Owned by someone else — must be filtered out.
                    "entity_type": "docx",
                    "title_highlighted": "他人 doc",
                    "summary_highlighted": "",
                    "result_meta": {
                        "token": "doxcnxxxxxxxxxxxx",
                        "owner_id": "ou_zzzzzzzzzzzzzzzz",  # sanitize: allow-line test fixture
                        "doc_types": "docx",
                        "url": "https://example.com/docx/zzz",
                        "create_time_iso": "2026-04-10T10:00:00+08:00",
                        "update_time_iso": "2026-04-12T10:00:00+08:00",
                    },
                },
            ],
            "has_more": False,
            "page_token": "",
        }}

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = docs_owned.DocsOwnedAdapter().fetch(_ctx())

    paths = [r.relative_path for r in result.raws]
    assert paths == ["docs/doxcnXXXXXXXXXXXX.md"]
    raw = result.raws[0]
    assert raw.source_type == "docs"
    # title is the highlight-stripped value
    assert "架构方案" in raw.content
    assert "<em>" not in raw.content
    fm = raw.frontmatter
    assert fm["doc_token"] == "doxcnXXXXXXXXXXXX"
    assert fm["doc_url"] == "https://example.com/docx/aaa"
    assert fm["doc_type"] == "docx"
    assert fm["author_open_id"] == "ou_xxxxxxxxxxxxxxxx"
    assert fm["modified_at"] == "2026-04-20T10:00:00+08:00"
    assert result.next_cursor["status"] == "ok"


def test_fetch_skips_when_search_lacks_permission(monkeypatch) -> None:
    def fake_run(args, **kw):
        raise lark_cli.LarkCliError("[403] permission denied for drive +search")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = docs_owned.DocsOwnedAdapter().fetch(_ctx())
    assert result.raws == []
    assert result.skipped_reason and "scope" in result.skipped_reason
    assert result.next_cursor.get("status") == "permission_blocked"
