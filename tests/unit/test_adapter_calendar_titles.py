"""Tests for adapters.calendar_titles (M2 alignment with real lark-cli surface).

Real CLI: `lark-cli calendar +agenda --start <iso> --end <iso>` → `{"data": [event...]}`.
Each event: `{event_id, summary, start_time: {datetime, timezone}, event_organizer:
{user_id, display_name}, ...}`. Adapter keeps only events where target is the organizer.
"""
from __future__ import annotations

import datetime as _dt

from clonemate import lark_cli
from clonemate.adapters import calendar_titles
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


def test_only_white_list_fields_kept(monkeypatch) -> None:
    """Even if lark-cli returns description/attachments, adapter must drop them."""
    def fake_run(args, **kw):
        assert args[:2] == ["calendar", "+agenda"]
        return {"data": [
            {
                "event_id": "e1",
                "summary": "周会",
                "start_time": {"datetime": "2026-04-15T10:00:00", "timezone": "Asia/Shanghai"},
                "event_organizer": {
                    "user_id": "ou_xxxxxxxxxxxxxxxx",
                    "display_name": "张三",
                },
                "description": "SECRET — should be discarded",
                "attachments": [{"name": "slides.pdf"}],
            },
            {
                # Event organized by someone else — must be filtered out.
                "event_id": "e2",
                "summary": "他人主持",
                "start_time": {"datetime": "2026-04-16T10:00:00", "timezone": "Asia/Shanghai"},
                "event_organizer": {
                    "user_id": "ou_zzzzzzzzzzzzzzzz",  # sanitize: allow-line test fixture
                    "display_name": "李四",
                },
            },
        ]}

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = calendar_titles.CalendarTitlesAdapter().fetch(_ctx())
    assert len(result.raws) == 1
    raw = result.raws[0]
    assert raw.source_type == "calendar"
    assert raw.relative_path == "calendar/2026-04.md"
    assert "周会" in raw.content
    assert "SECRET" not in raw.content
    assert "slides.pdf" not in raw.content
    # Other-organized event must not leak through.
    assert "他人主持" not in raw.content
    # Frontmatter only carries whitelisted event fields.
    assert "description" not in raw.frontmatter
    assert "attachments" not in raw.frontmatter
    for ev in raw.frontmatter["events"]:
        assert set(ev.keys()) <= {"event_id", "summary", "start_time", "event_organizer"}
    assert result.next_cursor.get("status") == "ok"


def test_fetch_skips_when_agenda_lacks_permission(monkeypatch) -> None:
    def fake_run(args, **kw):
        raise lark_cli.LarkCliError("[401] permission denied for calendar +agenda")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    result = calendar_titles.CalendarTitlesAdapter().fetch(_ctx())
    assert result.raws == []
    assert result.skipped_reason and "scope" in result.skipped_reason
    assert result.next_cursor.get("status") == "permission_blocked"
