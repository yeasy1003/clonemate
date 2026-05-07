"""rebind — change a vault's locked profile, requires new profile to
authenticate the same app_id (spec §8.7)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


class RebindAppIdMismatchError(RuntimeError):
    """Raised when the new profile's app_id differs from the vault's locked app_id."""


def _run_whoami(profile: str) -> subprocess.CompletedProcess[str]:
    """Mockable subprocess wrapper. Same pattern as profile_check._run_whoami."""
    return subprocess.run(
        ["lark-cli", "auth", "whoami", "--profile", profile, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )


def rebind(vault_dir: Path | str, *, new_profile: str) -> None:
    """Re-bind a vault to `new_profile`, requiring that the new profile
    authenticate the same `app_id` as the vault's locked identity.

    Codex round 1 Finding 6: rebind reads-and-writes _clone.yaml without
    a vault-level lock. CloneMate's documented concurrency assumption is
    "single-process CLI" — running rebind concurrently with sync/feed is
    user error. M2 fcntl locking is page-level (merge_note) only.
    Future hardening can add a vault-level _clone.yaml lock if needed.
    """
    vault_dir = Path(vault_dir)
    cy_path = vault_dir / "_clone.yaml"
    cy = yaml.safe_load(cy_path.read_text(encoding="utf-8"))
    expected_app_id = cy.get("identity", {}).get("app_id")
    if not expected_app_id:
        raise RebindAppIdMismatchError(f"{cy_path} has no identity.app_id")

    cp = _run_whoami(new_profile)
    if cp.returncode != 0:
        raise RebindAppIdMismatchError(
            f"`lark-cli auth whoami --profile {new_profile}` failed: "
            f"{cp.stderr.strip() or cp.stdout.strip()!r}. "
            f"Run `lark-cli auth login --profile {new_profile}` first."
        )
    try:
        whoami = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RebindAppIdMismatchError(
            f"`lark-cli auth whoami --json` invalid JSON: {exc}"
        ) from exc
    actual = whoami.get("app_id")
    if actual != expected_app_id:
        raise RebindAppIdMismatchError(
            f"refuse rebind: vault locked to app_id={expected_app_id!r}; "
            f"profile {new_profile!r} authenticates app_id={actual!r}. "
            f"Rebind requires the new profile share the same app_id."
        )
    cy["profile"] = new_profile
    cy_path.write_text(
        yaml.safe_dump(cy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
