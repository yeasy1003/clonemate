"""log_append — append-only vault timeline (spec §5.3).

Format: `## [YYYY-MM-DD HH:MM] <op> | <subject> | <metric>`
Grep recipe: `grep '^## \\[' log.md | tail -N`
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

_HEADER = "# Log\n"


def append(
    log_path: Path | str,
    *,
    op: str,
    subject: str,
    metric: str,
    now: _dt.datetime | None = None,
) -> None:
    """Append a single entry to log.md (creates the file with header if missing)."""
    log_path = Path(log_path)
    now = now or _dt.datetime.now().astimezone()
    ts = now.strftime("%Y-%m-%d %H:%M")
    line = f"## [{ts}] {op} | {subject} | {metric}\n"

    if not log_path.is_file():
        log_path.write_text(_HEADER + "\n" + line, encoding="utf-8")
        return

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
