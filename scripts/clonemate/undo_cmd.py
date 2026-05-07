"""undo — git revert HEAD + index rebuild (spec §6.7)."""
from __future__ import annotations

from pathlib import Path

import yaml


class NothingToUndoError(RuntimeError):
    """Codex round 1 Finding 5: root commit / empty repo has nothing to undo."""


def undo(vault_dir: Path | str) -> None:
    from clonemate import git_ops, index_upsert, log_append

    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))

    # Codex round 1 Finding 5 (HIGH): preflight — refuse to revert the root
    # commit (would delete the vault scaffold). Require ≥ 2 commits.
    if not (vault_dir / ".git").exists():
        raise NothingToUndoError(f"{vault_dir} is not a git repository")
    cp = git_ops.run(["rev-list", "--count", "HEAD"], cwd=vault_dir)
    try:
        commit_count = int(cp.stdout.strip())
    except ValueError as exc:
        raise NothingToUndoError(
            f"`git rev-list --count HEAD` in {vault_dir} returned non-numeric output: "
            f"{cp.stdout!r}"
        ) from exc
    if commit_count < 2:
        raise NothingToUndoError(
            f"vault has {commit_count} commit(s); need ≥ 2 to undo "
            f"(reverting the root commit would delete the vault scaffold)"
        )

    # `git revert HEAD --no-edit` — if HEAD is a merge, requires --mainline; spec
    # treats undo as the simple linear case. Bail with a clear error if revert
    # fails (e.g. merge HEAD or already-reverted state).
    try:
        git_ops.run(
            [
                "-c",
                "user.email=clonemate@local",
                "-c",
                "user.name=clonemate",
                "revert",
                "HEAD",
                "--no-edit",
            ],
            cwd=vault_dir,
        )
    except git_ops.GitError as exc:
        raise RuntimeError(f"undo failed: {exc}") from exc
    log = vault_dir / "log.md"
    index_upsert.rebuild(vault_dir, display_name=cy["display_name"], log_path=log)
    log_append.append(log, op="undo", subject=cy["slug"], metric="reverted HEAD")
    git_ops._auto_commit_vault(vault_dir, message="undo: index rebuilt + log appended")
