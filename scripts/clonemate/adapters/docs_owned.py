"""docs_owned adapter — list docs created/owned by target via drive +search.

Real CLI: `lark-cli drive +search --creator-ids <ou_xxx> --created-since <iso>
--doc-types docx,wiki,sheet --page-size 20 --page-token` returns
`data.{results[].{token, entity_type, result_meta.{owner_id, owner_name,
edit_user_id, doc_types, url, create_time_iso, update_time_iso, ...},
title_highlighted, summary_highlighted}}`.

Filter to results where `result_meta.owner_id == target.open_id` (creator-ids
returns docs created by, but ownership may have transferred).

Body fetch (`docs +fetch --doc <token>`) is intentionally deferred to ingest
phase — storing only metadata in raw/ keeps sync fast and avoids quota burn.
The `doc_token` in frontmatter lets ingest pull the body on demand.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

from clonemate import lark_cli
from clonemate.adapters._base import AdapterResult, FetchContext
from clonemate.adapters._perm import is_permission_error
from clonemate.raw_writer import RawCandidate

_HIGHLIGHT_RE = re.compile(r"<[^>]+>")


def _strip_highlight(s: str) -> str:
    return _HIGHLIGHT_RE.sub("", s or "")


class DocsOwnedAdapter:
    name: str = "docs_owned"

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        since_iso = ctx.since.isoformat()
        results: list[dict[str, Any]] = []
        page_token: str | None = None
        try:
            while True:
                args = [
                    "drive", "+search",
                    "--creator-ids", ctx.open_id,
                    "--created-since", since_iso,
                    "--doc-types", "docx,wiki,sheet",
                    "--page-size", "20",
                    "--query", "",
                ]
                if page_token:
                    args += ["--page-token", page_token]
                resp = lark_cli.run(args, profile=ctx.profile)["data"]
                results.extend(resp.get("results", []) or [])
                if not resp.get("has_more"):
                    break
                page_token = resp.get("page_token")
                if not page_token:
                    break
                # Bound: don't paginate beyond reasonable count.
                if len(results) >= 200:
                    break
        except lark_cli.LarkCliError as exc:
            if is_permission_error(str(exc)):
                return AdapterResult(
                    raws=[],
                    next_cursor={"status": "permission_blocked", "reason": str(exc)},
                    skipped_reason=f"missing scope for drive +search: {exc}",
                )
            raise

        # Filter to docs target actually owns (creator != owner is possible).
        owned = [
            r for r in results
            if (r.get("result_meta") or {}).get("owner_id") == ctx.open_id
        ]
        if not owned:
            return AdapterResult(raws=[], next_cursor={"status": "ok"})

        candidates: list[RawCandidate] = []
        now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        for r in owned:
            meta = r.get("result_meta", {}) or {}
            tok = meta.get("token")
            if not tok:
                continue
            title = _strip_highlight(r.get("title_highlighted", "")) or tok
            doc_type = (meta.get("doc_types") or r.get("entity_type") or "?").lower()
            body = [
                f"# {title}",
                "",
                f"链接: {meta.get('url', '')}",
                f"类型: {doc_type}",
                f"创建于: {meta.get('create_time_iso', '')}",
                f"更新于: {meta.get('update_time_iso', '')}",
                f"摘要: {_strip_highlight(r.get('summary_highlighted', ''))}",
            ]
            fm = {
                "fetched_at": now,
                "title": title,
                "doc_token": tok,
                "doc_type": doc_type,
                "doc_url": meta.get("url"),
                "modified_at": meta.get("update_time_iso"),
                "author_open_id": ctx.open_id,
            }
            candidates.append(RawCandidate(
                source_type="docs",
                relative_path=f"docs/{tok}.md",
                hash_input=f"{tok}|{meta.get('update_time_iso', '')}",
                frontmatter=fm,
                content="\n".join(body) + "\n",
            ))

        return AdapterResult(
            raws=candidates,
            next_cursor={"status": "ok", "last_modified_at": now},
        )
