"""minutes adapter — list minutes where target is owner or participant.

Real CLI: `lark-cli minutes +search --owner-ids <ou_xxx> --start <date>
--page-size 30 --page-token` returns `data.{items[], has_more, page_token}`.
Each item: `{token, display_info, meta_data.{app_link, description, avatar}}`.
display_info contains title + owner + start_time + duration in human-readable form.

We do NOT download audio/video media or transcripts (out of MVP scope —
those need separate `minutes +download` calls and produce large files).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from clonemate import lark_cli
from clonemate.adapters._base import AdapterResult, FetchContext
from clonemate.adapters._perm import is_permission_error
from clonemate.raw_writer import RawCandidate


def _search_minutes(
    *, role_flag: str, target_open_id: str, start_iso: str, profile: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        args = [
            "minutes", "+search",
            role_flag, target_open_id,
            "--start", start_iso,
            "--page-size", "30",
        ]
        if page_token:
            args += ["--page-token", page_token]
        resp = lark_cli.run(args, profile=profile)["data"]
        items.extend(resp.get("items", []) or [])
        if not resp.get("has_more"):
            break
        page_token = resp.get("page_token")
        if not page_token:
            break
    return items


class MinutesAdapter:
    name: str = "minutes"

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        start_iso = ctx.since.date().isoformat()  # YYYY-MM-DD per CLI help
        try:
            owner_items = _search_minutes(
                role_flag="--owner-ids",
                target_open_id=ctx.open_id,
                start_iso=start_iso,
                profile=ctx.profile,
            )
            participant_items = _search_minutes(
                role_flag="--participant-ids",
                target_open_id=ctx.open_id,
                start_iso=start_iso,
                profile=ctx.profile,
            )
        except lark_cli.LarkCliError as exc:
            if is_permission_error(str(exc)):
                return AdapterResult(
                    raws=[],
                    next_cursor={"status": "permission_blocked", "reason": str(exc)},
                    skipped_reason=f"missing scope for minutes +search: {exc}",
                )
            raise

        seen: dict[str, dict[str, Any]] = {}
        for item in [*owner_items, *participant_items]:
            token = item.get("token")
            if token:
                seen.setdefault(token, item)

        if not seen:
            return AdapterResult(raws=[], next_cursor={"status": "ok"})

        candidates: list[RawCandidate] = []
        now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        for token, m in sorted(seen.items()):
            display = m.get("display_info", "") or ""
            meta = m.get("meta_data", {}) or {}
            app_link = meta.get("app_link", "")
            description = meta.get("description", "")
            # display_info typically: "<title>\n关键词: ...\n所有者: ... 开始时间: ... 时长: ..."
            title_line = display.split("\n", 1)[0] if display else token
            body = [
                f"# {title_line}",
                "",
                f"链接: {app_link}",
                f"描述: {description}",
                "",
                "## 概览",
                display,
            ]
            fm = {
                "fetched_at": now,
                "title": title_line,
                "minute_token": token,
                "url": app_link,
                "author_open_id": ctx.open_id,
                "is_owner": any(it.get("token") == token for it in owner_items),
                "is_participant": any(it.get("token") == token for it in participant_items),
            }
            candidates.append(RawCandidate(
                source_type="minutes",
                relative_path=f"minutes/{token}.md",
                hash_input="\n".join(body),
                frontmatter=fm,
                content="\n".join(body) + "\n",
            ))

        return AdapterResult(
            raws=candidates,
            next_cursor={"status": "ok", "last_synced_at": now},
        )
