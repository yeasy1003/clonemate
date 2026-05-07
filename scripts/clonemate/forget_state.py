"""Durable forget-state for Level 2 crash recovery (Codex round 1 Findings 2+4+6).

Level 2 has a pause point between `start` (delete raw, audit pages, emit prompt)
and `finish` (filter-repo). State is saved to `<vault>/.forget-state/<source>.json`
so re-running `start` is idempotent and `finish` knows what to scrub from history.

`.forget-state/` is .gitignored — pure transient state.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ForgetState:
    source: str
    started_at: str
    raw_snippets: list[str] = field(default_factory=list)
    dirty_pages: list[str] = field(default_factory=list)


def _state_dir(vault_dir: Path | str) -> Path:
    return Path(vault_dir) / ".forget-state"


def _state_path(vault_dir: Path | str, source: str) -> Path:
    return _state_dir(vault_dir) / f"{source}.json"


def save(vault_dir: Path | str, state: ForgetState) -> None:
    """Codex round 4 Issue-H (MED): atomic write — write to .tmp + rename.
    A mid-write crash leaves either the old state or no state, never a
    truncated file. (POSIX rename is atomic on the same filesystem.)"""
    sd = _state_dir(vault_dir)
    sd.mkdir(exist_ok=True)
    # Always ensure .gitignore is present
    (sd / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    target = _state_path(vault_dir, state.source)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(target)


def load(vault_dir: Path | str, *, source: str) -> ForgetState | None:
    """Codex round 3 Issue-E/I: defensive parsing — uses .get() for ALL
    keys so future schema additions or partial writes don't raise KeyError.
    Returns None on any unrecoverable error."""
    p = _state_path(vault_dir, source)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    src = data.get("source")
    if not isinstance(src, str) or not src:
        return None  # required field missing or empty
    return ForgetState(
        source=src,
        started_at=str(data.get("started_at") or ""),
        raw_snippets=list(data.get("raw_snippets") or []),
        dirty_pages=list(data.get("dirty_pages") or []),
    )


def clear(vault_dir: Path | str, *, source: str) -> None:
    p = _state_path(vault_dir, source)
    p.unlink(missing_ok=True)
