"""im_1v1 adapter — fetch p2p messages between caller and target.

Real CLI: `lark-cli im +chat-messages-list --user-id <ou_target> --start <iso>
--end <iso> --page-size 50 --page-token <token>` resolves the p2p chat
automatically and returns `data.{messages, has_more, page_token, total}`.
Each message: `{content, create_time, message_id, msg_type, sender.{id, name}}`.

Partitioned by year-month. Cursor stores last seen message_id (just informational
since we re-query by time window each sync).
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any

from clonemate import lark_cli
from clonemate.adapters._base import AdapterResult, FetchContext
from clonemate.adapters._perm import is_permission_error
from clonemate.raw_writer import RawCandidate


def _parse_create_time(s: str) -> _dt.datetime:
    """Lark CLI returns 'YYYY-MM-DD HH:MM' (no seconds, no tz). Treat as local."""
    try:
        return _dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except ValueError:
        return _dt.datetime.fromisoformat(s)


class Im1v1Adapter:
    name: str = "im_1v1"

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        end = _dt.datetime.now(tz=ctx.since.tzinfo or _dt.timezone.utc)
        start = ctx.since
        max_msgs = int(ctx.quota.get("per_source_max_messages", 1000))

        all_msgs: list[dict[str, Any]] = []
        page_token: str | None = None
        try:
            while True:
                args = [
                    "im", "+chat-messages-list",
                    "--user-id", ctx.open_id,
                    "--start", start.isoformat(),
                    "--end", end.isoformat(),
                    "--page-size", "50",
                    "--sort", "asc",
                ]
                if page_token:
                    args += ["--page-token", page_token]
                resp = lark_cli.run(args, profile=ctx.profile)["data"]
                all_msgs.extend(resp.get("messages", []) or [])
                if len(all_msgs) >= max_msgs:
                    all_msgs = all_msgs[:max_msgs]
                    break
                if not resp.get("has_more"):
                    break
                page_token = resp.get("page_token")
                if not page_token:
                    break
        except lark_cli.LarkCliError as exc:
            if is_permission_error(str(exc)):
                return AdapterResult(
                    raws=[],
                    next_cursor={"status": "permission_blocked", "reason": str(exc)},
                    skipped_reason=f"missing scope for im 1v1: {exc}",
                )
            raise

        if not all_msgs:
            return AdapterResult(raws=[], next_cursor={"status": "ok", "chat_to_msg": {}})

        by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in all_msgs:
            ts = _parse_create_time(m.get("create_time", ""))
            by_month[f"{ts.year:04d}-{ts.month:02d}"].append(m)

        now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        candidates: list[RawCandidate] = []
        for ym, msgs in sorted(by_month.items()):
            body_lines = []
            for m in msgs:
                sender = m.get("sender", {}) or {}
                author = sender.get("id", "?")
                ts = m.get("create_time", "")
                content = m.get("content", "")
                body_lines.append(f"> author={author} ({ts}): {content}")
            fm = {
                "fetched_at": now,
                "title": f"{ctx.open_id} 1v1 chat {ym}",
                "participants": [ctx.my_open_id, ctx.open_id],
                "window": {
                    "start": msgs[0].get("create_time", ""),
                    "end": msgs[-1].get("create_time", ""),
                },
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
                source_type="im_1v1",
                relative_path=f"im_1v1/{ctx.open_id}/{ym}.md",
                hash_input="\n".join(body_lines),
                frontmatter=fm,
                content="\n".join(body_lines) + "\n",
            ))

        return AdapterResult(
            raws=candidates,
            next_cursor={
                "status": "ok",
                "chat_to_msg": {ctx.open_id: all_msgs[-1].get("message_id", "")},
            },
        )
