"""calendar_titles adapter — list calendar events where target is the organizer.

Real CLI: `lark-cli calendar +agenda --start <iso> --end <iso>` returns the
caller's primary calendar events. Each event has `event_organizer.user_id`
but does NOT include attendee list at this granularity.

For MVP we only filter to events where target IS the organizer (skipping
events where target is just an attendee — that requires per-event
`calendar event.attendees list`, deferred to a future iteration).

Spec §8.4 red line: only `event_id`, `summary`, `start_time`, organizer.
NEVER export `description` or `attachments`.
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any

from clonemate import lark_cli
from clonemate.adapters._base import AdapterResult, FetchContext
from clonemate.adapters._perm import is_permission_error
from clonemate.raw_writer import RawCandidate

_ALLOWED_FIELDS = ("event_id", "summary", "start_time", "event_organizer")


def _start_iso(e: dict[str, Any]) -> str:
    """Calendar +agenda returns start_time as {datetime, timezone} dict."""
    s = e.get("start_time", {}) or {}
    if isinstance(s, dict):
        return s.get("datetime", "")
    return str(s)


class CalendarTitlesAdapter:
    name: str = "calendar_titles"

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        end = _dt.datetime.now(tz=ctx.since.tzinfo or _dt.timezone.utc)
        try:
            resp = lark_cli.run(
                [
                    "calendar", "+agenda",
                    "--start", ctx.since.isoformat(),
                    "--end", end.isoformat(),
                ],
                profile=ctx.profile,
            )
        except lark_cli.LarkCliError as exc:
            if is_permission_error(str(exc)):
                return AdapterResult(
                    raws=[],
                    next_cursor={"status": "permission_blocked", "reason": str(exc)},
                    skipped_reason=f"missing scope for calendar +agenda: {exc}",
                )
            raise

        events = resp.get("data", []) or []
        # Keep only events where target is the organizer.
        target_events = [
            e for e in events
            if (e.get("event_organizer") or {}).get("user_id") == ctx.open_id
        ]
        if not target_events:
            return AdapterResult(raws=[], next_cursor={"status": "ok"})

        # Strip to allowed fields.
        filtered = [{k: e.get(k) for k in _ALLOWED_FIELDS} for e in target_events]

        # Group by year-month based on start.
        by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in filtered:
            ym = _start_iso(e)[:7] or "unknown"
            by_month[ym].append(e)

        candidates: list[RawCandidate] = []
        now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        for ym, evs in sorted(by_month.items()):
            body = [f"# Calendar — {ym}", ""]
            for e in evs:
                organizer = (e.get("event_organizer") or {}).get("display_name", "")
                body.append(
                    f"- {_start_iso(e)}  {e.get('summary', '')}  organizer={organizer}"
                )
            fm = {
                "fetched_at": now,
                "title": f"Calendar {ym}",
                "author_open_id": ctx.open_id,
                "month": ym,
                "events": filtered,
            }
            candidates.append(RawCandidate(
                source_type="calendar",
                relative_path=f"calendar/{ym}.md",
                hash_input="\n".join(body),
                frontmatter=fm,
                content="\n".join(body) + "\n",
            ))
        return AdapterResult(raws=candidates, next_cursor={"status": "ok"})
