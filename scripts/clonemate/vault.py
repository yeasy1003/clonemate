"""vault — single source of truth for vault initialization, identity lookup,
and path resolution. wiki/index/log writes do NOT live here (see merge_note,
index_upsert, log_append in later milestones).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

import yaml

from clonemate import git_ops
from clonemate._version import __version__

_WIKI_SUBDIRS = ("entities", "concepts", "syntheses", "sources")


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_template(name: str) -> str:
    return (Path(__file__).parent.parent.parent / "templates" / name).read_text(encoding="utf-8")


def _render(template_text: str, mapping: dict[str, Any]) -> str:
    out = template_text
    for k, v in mapping.items():
        out = out.replace("{{ " + k + " }}", str(v))
    return out


def init(
    *,
    vault_dir: Path,
    slug: str,
    open_id: str,
    app_id: str,
    display_name: str,
    profile: str,
    union_id: str | None = None,
    user_id: str | None = None,
    aliases: list[str] | None = None,
) -> None:
    """Create a fresh vault at vault_dir."""
    git_ops.check_filter_repo()

    vault_dir = Path(vault_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Directory tree
    (vault_dir / "raw").mkdir(exist_ok=True)
    for sub in _WIKI_SUBDIRS:
        (vault_dir / "wiki" / sub).mkdir(parents=True, exist_ok=True)

    # Metadata files
    now = _now_iso()
    aliases_list = aliases or [display_name]
    clone_yaml: dict[str, Any] = {
        "slug": slug,
        "identity": {
            "open_id": open_id,
            "app_id": app_id,
            "union_id": union_id,
            "user_id": user_id,
        },
        "display_name": display_name,
        "aliases": aliases_list,
        "created_at": now,
        "last_sync_run_at": now,
        "cursors": {
            "contact": {"status": "pending"},
            "im_1v1": {"chat_to_msg": {}, "status": "pending"},
            "im_group": {"chat_to_msg": {}, "status": "pending"},
            "minutes": {"status": "pending"},
            "docs_owned": {"status": "pending"},
            "doc_comments": {"doc_to_comment_id": {}, "status": "pending"},
            "calendar": {"status": "pending"},
            "meego": {"status": "skipped"},
        },
        "sources_enabled": {
            "contact": True,
            "im_1v1": True,
            "im_group": True,
            "minutes": True,
            "docs_owned": True,
            "doc_comments": True,
            "calendar_titles": True,
            "meego": False,
        },
        "window": {"default_since": "180d"},
        "profile": profile,
        "quota": {"per_source_max_messages": 1000, "per_source_max_mb": 100},
        "filters": {
            "im_group": {
                "require_signal": ["@mention", "quoted", "self_message"],
                "context_window": 20,
            },
            "calendar": {"skip_keywords": []},
        },
        "plugins_allowed": [],
    }
    (vault_dir / "_clone.yaml").write_text(
        yaml.safe_dump(clone_yaml, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    (vault_dir / "index.md").write_text(
        _render(_read_template("index.md.tmpl"), {"display_name": display_name, "now": now}),
        encoding="utf-8",
    )
    (vault_dir / "log.md").write_text(
        f"# Log\n\n## [{now}] init | {slug} | new vault\n",
        encoding="utf-8",
    )
    (vault_dir / "SKILL.md").write_text(
        _render(_read_template("SKILL.md.tmpl"), {"display_name": display_name, "slug": slug}),
        encoding="utf-8",
    )
    (vault_dir / ".clonemate-version").write_text(__version__ + "\n", encoding="utf-8")

    # Git
    git_ops.init_vault_repo(vault_dir)
    _write_vault_gitignore(vault_dir)
    git_ops.install_pre_push_hook(vault_dir)


def list_vaults(root: Path) -> list[dict[str, Any]]:
    """List all vaults under `root` (directories containing _clone.yaml)."""
    root = Path(root)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        cy = entry / "_clone.yaml"
        if not cy.is_file():
            continue
        try:
            data = yaml.safe_load(cy.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and "slug" in data:
            out.append(data)
    return out


def iter_vaults_under_root(root: Path | str) -> list[Path]:
    """List vault directories under `root`. A vault is a direct child
    directory of `root` that contains `_clone.yaml`. Non-recursive — does
    not look inside vaults for nested vaults.

    Spec §6.5 Level 1: used to scrub cross-vault syntheses references when
    a vault is forgotten."""
    root = Path(root)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "_clone.yaml").is_file():
            out.append(child)
    return out


def rename(*, root: Path, old_slug: str, new_slug: str) -> Path:
    """Rename a vault: move directory + update _clone.yaml.slug."""
    root = Path(root)
    src = root / old_slug
    dst = root / new_slug
    if not (src / "_clone.yaml").is_file():
        raise FileNotFoundError(f"no vault at {src}")
    if dst.exists():
        raise FileExistsError(f"{dst} already exists")
    src.rename(dst)
    cy = dst / "_clone.yaml"
    data = yaml.safe_load(cy.read_text(encoding="utf-8"))
    data["slug"] = new_slug
    cy.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return dst


def _write_vault_gitignore(vault_dir: Path) -> None:
    """Vault-internal .gitignore — raw/ MUST be excluded so deletion is true delete."""
    (vault_dir / ".gitignore").write_text(
        "# CloneMate vault — raw is the immutable source-of-truth and is\n"
        "# physically deleted on `forget --source` (no git history retains it).\n"
        "raw/\n"
        "*.error.log\n"
        ".cache/\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clonemate.vault")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--root", required=True)
    p_init.add_argument("--slug", required=True)
    p_init.add_argument("--open-id", required=True)
    p_init.add_argument("--app-id", required=True)
    p_init.add_argument("--display-name", required=True)
    p_init.add_argument("--profile", default="claude-code")
    p_init.add_argument("--union-id", default=None)
    p_init.add_argument("--user-id", default=None)
    p_init.add_argument("--alias", action="append", default=None)

    p_list = sub.add_parser("list")
    p_list.add_argument("--root", required=True)

    p_rename = sub.add_parser("rename")
    p_rename.add_argument("--root", required=True)
    p_rename.add_argument("--old-slug", required=True)
    p_rename.add_argument("--new-slug", required=True)

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.cmd == "init":
        init(
            vault_dir=Path(args.root) / args.slug,
            slug=args.slug,
            open_id=args.open_id,
            app_id=args.app_id,
            display_name=args.display_name,
            profile=args.profile,
            union_id=args.union_id,
            user_id=args.user_id,
            aliases=args.alias,
        )
        print(f"OK: vault initialized at {Path(args.root) / args.slug}")
        return 0
    if args.cmd == "list":
        vaults = list_vaults(Path(args.root))
        if not vaults:
            print("no vaults under", args.root)
            return 0
        for v in vaults:
            print(f"{v['slug']:20s}  {v.get('display_name','')}  ({v['identity']['open_id']})")
        return 0
    if args.cmd == "rename":
        new_dir = rename(root=Path(args.root), old_slug=args.old_slug, new_slug=args.new_slug)
        print(f"OK: renamed to {new_dir}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
