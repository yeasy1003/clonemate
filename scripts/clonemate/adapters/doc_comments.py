"""doc_comments adapter — fetch comments on docs that target owns.

Real CLI: `lark-cli drive file.comments list --params '{"file_token":"<tok>",
"file_type":"docx"}'` returns the doc's comment list. We then filter to
comments authored by target.

Consumes `doc_tokens_to_scan` from cursor (populated by docs_owned in the
same sync run).
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from clonemate import lark_cli
from clonemate.adapters._base import AdapterResult, FetchContext
from clonemate.adapters._perm import is_permission_error
from clonemate.raw_writer import RawCandidate


def _list_comments(file_token: str, *, file_type: str, profile: str) -> list[dict[str, Any]]:
    params = json.dumps({"file_token": file_token, "file_type": file_type})
    resp = lark_cli.run(
        ["drive", "file.comments", "list", "--params", params],
        profile=profile,
    )
    data = resp.get("data", {}) or {}
    return data.get("items", []) or []


class DocCommentsAdapter:
    name: str = "doc_comments"

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        # Newer fetch_sources passes typed entries; fall back to legacy token list.
        entries = ctx.cursor.get("doc_entries_to_scan", []) or []
        if not entries:
            entries = [
                {"token": t, "doc_type": "docx"}
                for t in (ctx.cursor.get("doc_tokens_to_scan", []) or [])
            ]
        last_seen: dict[str, str] = dict(ctx.cursor.get("doc_to_comment_id", {}) or {})
        candidates: list[RawCandidate] = []
        now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        per_doc_errors: dict[str, str] = {}

        for entry in entries:
            token = entry.get("token")
            doc_type = (entry.get("doc_type") or "docx").lower()
            # Wiki nodes wrap an underlying docx — comments don't attach to the
            # wiki token itself; skip rather than burn a failed call.
            if doc_type in ("wiki",):
                continue
            try:
                items = _list_comments(token, file_type=doc_type, profile=ctx.profile)
            except lark_cli.LarkCliError as exc:
                if is_permission_error(str(exc)):
                    return AdapterResult(
                        raws=[],
                        next_cursor={"status": "permission_blocked", "reason": str(exc)},
                        skipped_reason=f"missing scope for drive file.comments list: {exc}",
                    )
                per_doc_errors[token] = str(exc)
                continue

            if not items:
                continue

            # Keep only comments authored by target.
            mine = [c for c in items if c.get("user_id") == ctx.open_id]
            if not mine:
                continue

            body = [f"# 评论 — {token}", ""]
            for c in mine:
                # Comment text lives under reply_list[].reply.content (varies by API).
                replies = c.get("reply_list", {}).get("replies", []) or []
                texts: list[str] = []
                for r in replies:
                    if r.get("user_id") != ctx.open_id:
                        continue
                    content = r.get("content", {}) or {}
                    elements = content.get("elements", []) or []
                    for el in elements:
                        if el.get("type") == "text_run":
                            texts.append((el.get("text_run") or {}).get("text", ""))
                if not texts:
                    continue
                body.append(f"- author={ctx.open_id} ({c.get('create_time', '')}): {' '.join(texts)}")

            if len(body) <= 2:
                continue

            fm = {
                "fetched_at": now,
                "title": f"comments on {token}",
                "doc_token": token,
                "comments": [
                    {
                        "comment_id": c.get("comment_id"),
                        "author_open_id": ctx.open_id,
                        "ts": c.get("create_time"),
                    }
                    for c in mine
                ],
            }
            candidates.append(RawCandidate(
                source_type="comments",
                relative_path=f"comments/{token}.md",
                hash_input="\n".join(body),
                frontmatter=fm,
                content="\n".join(body) + "\n",
            ))
            if mine:
                last_seen[token] = mine[-1].get("comment_id", "")

        next_cursor: dict[str, Any] = {
            "doc_to_comment_id": last_seen,
            "status": "partial" if per_doc_errors else "ok",
        }
        if per_doc_errors:
            next_cursor["per_doc_errors"] = per_doc_errors
        return AdapterResult(raws=candidates, next_cursor=next_cursor)
