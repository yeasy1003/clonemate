"""git_ops — single source of truth for git subprocess invocations.

All git interactions in clonemate go through `git_ops.run`. This makes them
mockable in tests and keeps subprocess details out of vault.py / forget.py.
"""
from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git command exits non-zero."""


class MissingDependencyError(RuntimeError):
    """Raised when a required external tool is missing."""


def run(args: Sequence[str], cwd: Path | str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run `git <args...>` inside `cwd` and return CompletedProcess.

    Raises GitError when git exits non-zero (unless check=False).
    """
    cmd = ["git", *args]
    cp = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if check and cp.returncode != 0:
        raise GitError(f"`{' '.join(cmd)}` failed: {cp.stderr.strip() or cp.stdout.strip()}")
    return cp


def init_vault_repo(vault_dir: Path | str) -> None:
    """Run `git init --quiet` in vault_dir."""
    run(["init", "--quiet"], cwd=vault_dir)


def check_filter_repo() -> None:
    """Verify `git-filter-repo` is installed; raise MissingDependencyError otherwise."""
    try:
        cp = subprocess.run(
            ["git-filter-repo", "--version"], capture_output=True, text=True
        )
    except FileNotFoundError as exc:
        raise MissingDependencyError(
            "git-filter-repo is required for forget --source. Install with "
            "`brew install git-filter-repo` (macOS) or `pip install git-filter-repo`."
        ) from exc
    if cp.returncode != 0:
        raise MissingDependencyError(f"git-filter-repo present but failed: {cp.stderr.strip()}")


_PRE_PUSH_HOOK = """#!/bin/sh
echo "[clonemate] this vault is local-only; push is refused by design."
echo "If you really mean it, delete .git/hooks/pre-push manually."
exit 1
"""


def install_pre_push_hook(vault_dir: Path | str) -> None:
    """Write an executable pre-push hook that refuses any push."""
    hooks_dir = Path(vault_dir) / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "pre-push"
    hook.write_text(_PRE_PUSH_HOOK, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | 0o111)


# Vault git identity fallback when global config is missing.
# Spec §3 decision 15: vault is local-only, never pushed; identity is
# cosmetic, but git refuses to commit without one.
_VAULT_COMMIT_IDENTITY = ["-c", "user.email=clonemate@local", "-c", "user.name=clonemate"]


def _auto_commit_vault(vault_dir: Path | str, *, message: str) -> None:
    """Commit all current changes in vault_dir with `message`.

    Codex round 4 Finding 11: distinguishes "nothing to commit" (silent skip)
    from real failures (raised). Uses `git diff --cached --quiet` post-add to
    detect empty diffs without parsing fragile commit error messages, and
    passes `-c user.email/.name` identity so commits succeed in CI / fresh
    environments without global git config.
    """
    vault_dir = Path(vault_dir)
    # Stage everything first (real failure here MUST raise)
    run(["add", "."], cwd=vault_dir)
    # Empty-diff check: 0 == no diff in index, 1 == has diff. anything else is error.
    cp = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(vault_dir),
        capture_output=True,
        text=True,
    )
    if cp.returncode == 0:
        return  # nothing to commit — idempotent re-run
    if cp.returncode != 1:
        raise GitError(
            f"`git diff --cached --quiet` in {vault_dir} returned "
            f"{cp.returncode}: {cp.stderr.strip() or cp.stdout.strip()}"
        )
    # Real commit (with identity fallback)
    run([*_VAULT_COMMIT_IDENTITY, "commit", "-m", message], cwd=vault_dir)


def rewrite_history_replace_text(
    vault_dir: Path | str,
    *,
    replacements: Sequence[tuple[str, str]],
) -> None:
    """Wrap `git filter-repo --replace-text <file>`.

    `replacements` is a list of (literal pattern, replacement) pairs. The
    function writes them to a temp file in the format filter-repo expects
    (`pattern==>replacement` per line) and invokes filter-repo with
    `--force` so it works on a vault that has been modified since clone.

    Spec §6.5 Level 2: this is the destructive history-rewrite step. Live
    state should already be src-XXX-free before this runs (Claude has
    rewritten the dirty pages); filter-repo retroactively scrubs the
    older commits that still contained src-XXX references / content.

    Raises GitError when filter-repo exits non-zero or vault_dir is not a
    git repo.
    """
    vault_dir = Path(vault_dir)
    if not (vault_dir / ".git").exists():
        raise GitError(f"{vault_dir} is not a git repository")
    if not replacements:
        return
    # Write replacements file. filter-repo's expected format (per its docs):
    #   <pattern>==><replacement>
    # one per line. `==>` is the literal separator; pattern is treated as a
    # literal substring match unless prefixed with `regex:` or `glob:`.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    ) as fp:
        for pattern, replacement in replacements:
            fp.write(f"{pattern}==>{replacement}\n")
        replace_text_path = fp.name
    try:
        cp = subprocess.run(
            [
                "git-filter-repo",
                "--replace-text", replace_text_path,
                "--force",   # vault was cloned-via-init, not a fresh clone
            ],
            cwd=str(vault_dir),
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            raise GitError(
                f"git-filter-repo --replace-text failed in {vault_dir}: "
                f"{cp.stderr.strip() or cp.stdout.strip()}"
            )
    finally:
        Path(replace_text_path).unlink(missing_ok=True)
