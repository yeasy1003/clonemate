"""Profile validation gate for sync/feed (spec §8.7).

Each vault's `_clone.yaml.profile` locks the lark-cli profile used at vault
creation. Subsequent sync/feed calls MUST validate that the active lark-cli
auth state matches — otherwise data fetched would attribute the wrong
identity to raw, which violates the author-attribution red line (spec §8.5).

Validation: shell out to `lark-cli auth status --profile <vault.profile>`
(JSON by default) and compare returned `appId` against the vault's locked
`identity.app_id`.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


class ProfileMismatchError(RuntimeError):
    """Raised when lark-cli auth state does not match vault profile lock."""


def _run_whoami(profile: str) -> subprocess.CompletedProcess[str]:
    """Mockable subprocess wrapper. Returns CompletedProcess with JSON stdout.

    Calls `lark-cli auth status --profile <p>`; the CLI emits JSON by default.
    """
    return subprocess.run(
        ["lark-cli", "auth", "status", "--profile", profile],
        capture_output=True, text=True, check=False,
    )


def verify_profile(vault_dir: Path | str) -> None:
    """Verify lark-cli auth state matches vault's locked profile + app_id.

    Raises ProfileMismatchError on:
      - lark-cli auth status non-zero exit (profile not authenticated)
      - status JSON malformed
      - returned appId != vault's locked app_id

    Returns None on success.
    """
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    profile = cy.get("profile") or "claude-code"
    expected_app_id = cy.get("identity", {}).get("app_id")
    if not expected_app_id:
        raise ProfileMismatchError(
            f"{vault_dir}/_clone.yaml has no identity.app_id; cannot verify profile"
        )

    cp = _run_whoami(profile)
    if cp.returncode != 0:
        raise ProfileMismatchError(
            f"`lark-cli auth status --profile {profile}` failed: "
            f"{cp.stderr.strip() or cp.stdout.strip()!r}. "
            f"Run `lark-cli auth login --profile {profile}` first."
        )
    try:
        whoami = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise ProfileMismatchError(
            f"`lark-cli auth status` did not return valid JSON: {exc}"
        ) from exc
    actual_app_id = whoami.get("appId")
    if actual_app_id != expected_app_id:
        raise ProfileMismatchError(
            f"vault profile mismatch: vault locked to app_id={expected_app_id!r} "
            f"but profile {profile!r} authenticates app_id={actual_app_id!r}. "
            f"Either log in to the right profile (`lark-cli auth login --profile {profile}`) "
            f"or run `clonemate rebind --slug <slug> --profile <new>` if the new "
            f"profile shares the same app_id."
        )
