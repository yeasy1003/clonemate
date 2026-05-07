"""im_group adapter — find shared groups + filter to target's signal messages.

Real CLI:
  1. `lark-cli im +chat-search --member-ids <ou> --search-types
     public_joined,private --page-size 100` → list chats that user is in.
     We call this twice — once for target, once for caller — and intersect,
     so we only read chats both members share. Without this, we'd burn
     minutes paginating chats the caller has no read access to (every
     chat-messages-list there returns a permission error and is silently
     skipped, producing no data).
  2. Per shared chat: `lark-cli im +chat-messages-list --chat-id <oc_xxx>
     --start --end` → all messages in window.

Signal filter: keep only messages where sender.id == target_open_id (self_message).
Mention/quoted detection requires content parsing (lark CLI does not surface
explicit mention list at the message level), so we intentionally only match
self-authored messages for now and expand context window around them.
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any

from clonemate import lark_cli
from clonemate.adapters._base import AdapterResult, FetchContext
from clonemate.adapters._perm import is_permission_error
from clonemate.raw_writer import RawCandidate

_CONTEXT_WINDOW = 20


def _parse_create_time(s: str) -> _dt.datetime:
    try:
        return _dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except ValueError:
        return _dt.datetime.fromisoformat(s)


def _list_chats(open_id: str, profile: str) -> list[dict[str, Any]]:
    """Paginate chat-search; the Lark API caps offset at 200, so we stop when
    we hit code 1022 instead of bubbling the error."""
    chats: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        args = [
            "im", "+chat-search",
            "--member-ids", open_id,
            "--search-types", "public_joined,private",
            "--page-size", "100",
        ]
        if page_token:
            args += ["--page-token", page_token]
        try:
            resp = lark_cli.run(args, profile=profile)["data"]
        except lark_cli.LarkCliError as exc:
            if "1022" in str(exc) or "pagination limit" in str(exc).lower():
                break  # API offset cap reached — return what we have
            raise
        chats.extend(resp.get("chats", []) or [])
        if not resp.get("has_more"):
            break
        page_token = resp.get("page_token")
        if not page_token:
            break
    return chats


def _list_chat_messages(
    chat_id: str, *, start: _dt.datetime, end: _dt.datetime, profile: str, max_msgs: int,
) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        args = [
            "im", "+chat-messages-list",
            "--chat-id", chat_id,
            "--start", start.isoformat(),
            "--end", end.isoformat(),
            "--page-size", "50",
            "--sort", "asc",
        ]
        if page_token:
            args += ["--page-token", page_token]
        resp = lark_cli.run(args, profile=profile)["data"]
        msgs.extend(resp.get("messages", []) or [])
        if len(msgs) >= max_msgs:
            return msgs[:max_msgs]
        if not resp.get("has_more"):
            break
        page_token = resp.get("page_token")
        if not page_token:
            break
    return msgs


class ImGroupAdapter:
    name: str = "im_group"

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        end = _dt.datetime.now(tz=ctx.since.tzinfo or _dt.timezone.utc)
        start = ctx.since
        max_msgs = int(ctx.quota.get("per_source_max_messages", 1000))

        try:
            target_chats = _list_chats(ctx.open_id, ctx.profile)
            my_chats = _list_chats(ctx.my_open_id, ctx.profile)
        except lark_cli.LarkCliError as exc:
            if is_permission_error(str(exc)):
                return AdapterResult(
                    raws=[],
                    next_cursor={"status": "permission_blocked", "reason": str(exc)},
                    skipped_reason=f"missing scope for im chat-search: {exc}",
                )
            raise

        my_chat_ids = {c["chat_id"] for c in my_chats}
        chats = [c for c in target_chats if c["chat_id"] in my_chat_ids]

        candidates: list[RawCandidate] = []
        chat_to_last_msg: dict[str, str] = dict(ctx.cursor.get("chat_to_msg", {}))
        per_chat_errors: dict[str, str] = {}

        for chat in chats:
            chat_id = chat["chat_id"]
            try:
                messages = _list_chat_messages(
                    chat_id, start=start, end=end, profile=ctx.profile, max_msgs=max_msgs,
                )
            except lark_cli.LarkCliError as exc:
                # Skip chats we can't read (permission or other) but record.
                per_chat_errors[chat_id] = str(exc)
                continue

            if not messages:
                continue

            # Find indices where target is the sender.
            hit_idx = [
                i for i, m in enumerate(messages)
                if (m.get("sender") or {}).get("id") == ctx.open_id
            ]
            if not hit_idx:
                continue

            keep: set[int] = set()
            for i in hit_idx:
                for j in range(max(0, i - _CONTEXT_WINDOW), min(len(messages), i + _CONTEXT_WINDOW + 1)):
                    keep.add(j)
            kept = [messages[i] for i in sorted(keep)]

            by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for m in kept:
                ts = _parse_create_time(m.get("create_time", ""))
                by_month[f"{ts.year:04d}-{ts.month:02d}"].append(m)

            now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
            for ym, msgs in sorted(by_month.items()):
                body_lines = []
                for m in msgs:
                    sender = m.get("sender", {}) or {}
                    body_lines.append(
                        f"> author={sender.get('id', '?')} ({m.get('create_time', '')}): "
                        f"{m.get('content', '')}"
                    )
                fm = {
                    "fetched_at": now,
                    "title": f"{ctx.open_id} group {chat_id} {ym}",
                    "chat_id": chat_id,
                    "chat_name": chat.get("name", ""),
                    "filter_reasons": ["self_message"],
                    "context_window": _CONTEXT_WINDOW,
                    "messages": [
                        {
                            "author_open_id": (m.get("sender") or {}).get("id"),
                            "message_id": m.get("message_id"),
                            "ts": m.get("create_time"),
                        }
                        for m in msgs
                    ],
                }
                candidates.append(RawCandidate(
                    source_type="im_group",
                    relative_path=f"im_group/{chat_id}/{ym}.md",
                    hash_input="\n".join(body_lines),
                    frontmatter=fm,
                    content="\n".join(body_lines) + "\n",
                ))

            chat_to_last_msg[chat_id] = messages[-1].get("message_id", "")

        next_cursor: dict[str, Any] = {
            "status": "partial" if per_chat_errors else "ok",
            "chat_to_msg": chat_to_last_msg,
        }
        if per_chat_errors:
            next_cursor["per_chat_errors"] = per_chat_errors
        return AdapterResult(raws=candidates, next_cursor=next_cursor)
