"""lark_cli — single source of truth for lark-cli subprocess invocations.

All lark-cli calls in clonemate go through `lark_cli.run`. This makes them
mockable in tests, ensures `--profile` is always passed, and centralises
JSON parsing + error translation.
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

_DEFAULT_TIMEOUT_SEC = 180


class LarkCliError(RuntimeError):
    """Raised when lark-cli fails, times out, or returns non-JSON output."""


def run(
    args: Sequence[str],
    *,
    profile: str,
    timeout: int = _DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run `lark-cli <args...> --profile <profile>` and return parsed JSON.

    Raises LarkCliError on non-zero exit, timeout, or invalid JSON.
    """
    cmd = ["lark-cli", *args, "--profile", profile]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LarkCliError(f"`{' '.join(cmd)}` timed out after {timeout}s") from exc
    if cp.returncode != 0:
        raise LarkCliError(f"`{' '.join(cmd)}` exit={cp.returncode}: {cp.stderr.strip() or cp.stdout.strip()}")
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise LarkCliError(f"lark-cli stdout is not JSON: {cp.stdout[:200]!r}") from exc
