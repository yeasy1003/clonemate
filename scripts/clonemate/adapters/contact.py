"""contact adapter — fetch single profile via `lark-cli contact +get-user`.

Real CLI surface: `lark-cli contact +get-user --user-id <ou_xxx>` returns
`data.user.{name, user_id, i18n_name}`. Department / email / leader are NOT
returned by `+get-user` without extra scopes — when available we enrich
via `+search-user` (broader scope, returns `email`, `department`).
"""
from __future__ import annotations

import datetime as _dt

from clonemate import lark_cli
from clonemate.adapters._base import AdapterResult, FetchContext
from clonemate.adapters._perm import is_permission_error
from clonemate.raw_writer import RawCandidate


class ContactAdapter:
    name: str = "contact"

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        try:
            base = lark_cli.run(
                ["contact", "+get-user", "--user-id", ctx.open_id],
                profile=ctx.profile,
            )["data"]["user"]
        except lark_cli.LarkCliError as exc:
            if is_permission_error(str(exc)):
                return AdapterResult(
                    raws=[],
                    next_cursor={"status": "permission_blocked", "reason": str(exc)},
                    skipped_reason=f"missing scope for contact +get-user: {exc}",
                )
            raise

        # Enrich with +search-user (gives department, email when scope present).
        enriched: dict = {}
        try:
            search = lark_cli.run(
                ["contact", "+search-user", "--user-ids", ctx.open_id, "--as", "user"],
                profile=ctx.profile,
            )
            users = (search.get("data") or {}).get("users") or []
            if users:
                enriched = users[0]
        except lark_cli.LarkCliError:
            pass  # search-user may fail; base data is enough

        name = base.get("name") or enriched.get("localized_name") or ctx.open_id
        i18n = base.get("i18n_name", {}) or {}
        body_lines = [
            f"# {name}",
            "",
            f"open_id: {ctx.open_id}",
        ]
        if i18n.get("en_us"):
            body_lines.append(f"英文名: {i18n['en_us']}")
        if enriched.get("email"):
            body_lines.append(f"邮箱: {enriched['email']}")
        if enriched.get("department"):
            body_lines.append(f"部门: {enriched['department']}")

        now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        merged = {**enriched, **{k: v for k, v in base.items() if v}}
        cand = RawCandidate(
            source_type="contact",
            relative_path="contact/profile.md",
            hash_input=str(sorted(merged.items())),
            frontmatter={
                "fetched_at": now,
                "author_open_id": ctx.open_id,
                "title": f"{name} 档案",
            },
            content="\n".join(body_lines) + "\n",
        )
        return AdapterResult(
            raws=[cand],
            next_cursor={"status": "ok", "last_fetched_at": now},
        )
