"""raw_writer — single write entry-point for vault `raw/`.

- Computes content_hash via clonemate.content_hash
- Skips writing when the same hash already exists for that source_type
  (spec §7.2 — re-run sync should be idempotent)
- Assigns the next src_id by reading/writing vault/raw/.src_id_counter
- Path is rewritten from `<stem>.md` to `<stem>-<8 hex chars of sha256>.md` so
  two syncs hitting the same logical partition (e.g. im_1v1/<chat>/<ym>.md)
  with different message batches produce *different* files instead of
  overwriting each other (spec §3.1 raw 不可变, Codex review fix).
- Frontmatter MUST carry: src_id, source_type, content_hash + whatever the
  caller passed (fetched_at, origin, participants, author_open_id ...)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from clonemate import content_hash


@dataclass
class RawCandidate:
    source_type: str
    relative_path: str               # under vault/raw/, e.g. "im_1v1/oc_xxx/2026-04.md"
    hash_input: str                  # what to hash (stable across re-runs)
    frontmatter: dict[str, Any]      # writer adds src_id + content_hash
    content: str                     # markdown body


@dataclass
class WriteResult:
    written: bool                    # False = skipped (dup hash)
    skipped: bool                    # True if hash already known
    src_id: str                      # assigned or existing
    path: Path


class RawWriter:
    def __init__(self, vault_dir: Path | str) -> None:
        self.vault = Path(vault_dir)
        self._raw = self.vault / "raw"
        self._raw.mkdir(parents=True, exist_ok=True)

    def _next_src_id(self) -> str:
        counter_file = self._raw / ".src_id_counter"
        n = int(counter_file.read_text().strip()) if counter_file.is_file() else 0
        n += 1
        counter_file.write_text(str(n), encoding="utf-8")
        return f"src-{n:04d}"

    def _hashes_index(self, source_type: str) -> Path:
        d = self._raw / source_type
        d.mkdir(parents=True, exist_ok=True)
        return d / ".hashes.txt"

    def _hash_known(self, source_type: str, h: str) -> bool:
        idx = self._hashes_index(source_type)
        if not idx.is_file():
            return False
        return any(line.strip() == h for line in idx.read_text(encoding="utf-8").splitlines())

    def _record_hash(self, source_type: str, h: str) -> None:
        with self._hashes_index(source_type).open("a", encoding="utf-8") as fh:
            fh.write(h + "\n")

    def write(self, candidate: RawCandidate) -> WriteResult:
        """Write a raw file at {stem}-{hash_prefix}.md (raw is immutable)."""
        h = content_hash.compute(candidate.hash_input)
        hash_prefix = h.split(":", 1)[1][:8]
        stem = Path(candidate.relative_path)
        suffixed = stem.with_name(f"{stem.stem}-{hash_prefix}{stem.suffix}")
        target = self._raw / suffixed
        target.parent.mkdir(parents=True, exist_ok=True)

        if self._hash_known(candidate.source_type, h):
            # Same hash already written under a previous src_id; the on-disk
            # file at `target` is the existing one (path is hash-derived, so
            # identical hash -> identical path). Skip without re-writing.
            return WriteResult(written=False, skipped=True, src_id="", path=target)

        src_id = self._next_src_id()
        full_fm = {
            "src_id": src_id,
            "source_type": candidate.source_type,
            "content_hash": h,
            **candidate.frontmatter,
        }
        text = "---\n" + yaml.safe_dump(full_fm, allow_unicode=True, sort_keys=False) + "---\n\n" + candidate.content
        target.write_text(text, encoding="utf-8")
        self._record_hash(candidate.source_type, h)
        return WriteResult(written=True, skipped=False, src_id=src_id, path=target)
