"""merge_note — wiki single-writer entry-point.

Every write to vault/wiki/** goes through here. Subagents and tools MUST NOT
file.write_text the wiki directly. Invariants enforced in code (NOT prompts):

  1. frontmatter validation (page_type / confidence / author_role)
  2. **title path safety** — reject `/`, `..`, absolute paths
  3. **extra_frontmatter strict allow-list** (Codex Findings 6+12) — only keys
     in `_ALLOWED_EXTRA_FRONTMATTER` (currently `{few_shot_count: int}`) are
     permitted, with type check. Any unlisted key OR wrong type raises
     FrontmatterExtraKeyError. This covers both invariant-override attempts
     and arbitrary schema-drift.
  4. **pinned_fields default carry-forward** — caller passing pinned_fields=None
     means "keep existing pinned list". Only `pin()` / `unpin()` mutate it.
  5. **section-aware body merge** (Codex Findings 7+8):
       - pinned H2 section: ALWAYS carried forward from old body, even if new
         body omits the heading
       - non-pinned H2 in old but NOT in new: carry forward (don't lose data)
       - non-pinned H2 in new but NOT in old: include
       - same H2 in both: new wins, but `> ⚠️ CONFLICT: section <name> rewritten`
         marker injected for lint to surface
  6. **sources union** — new ∪ existing (sorted dedup)
  7. **voice red-line — code-enforced author filter** (spec §8.5 / Codex Find 9):
     for page_type='voice' with non-empty sources, caller MUST pass:
       - target_open_id
       - source_types_map[src_id] = source_type (allow-list check)
       - voice_evidence: list[{src_id, author_open_id, quote}] — every quote
         in body MUST have author_open_id == target_open_id
     Any non-target author raises VoiceSourceViolation.
  8. **atomic write** — tmp + rename
  9. **per-page fcntl.flock** — concurrent subagent writes serialize.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PAGE_TYPE_DIRS = {
    "persona":        ("wiki", "persona.md"),       # fixed filename
    "voice":          ("wiki", "voice.md"),         # fixed filename
    "entity":         ("wiki", "entities"),
    "concept":        ("wiki", "concepts"),
    "synthesis":      ("wiki", "syntheses"),
    "source_summary": ("wiki", "sources"),
}

_VALID_CONFIDENCE = {"high", "medium", "low"}
_VALID_AUTHOR_ROLES = {"ingest", "review", "query", "lint", "user"}
_VOICE_ALLOWED_SOURCE_TYPES = {"im_1v1", "im_group", "minutes", "doc_comments", "comments"}

# Codex Finding 12 (round 3): allow-list, NOT blocklist. Adding a key here is
# a deliberate schema decision. Each entry maps key -> required type.
_ALLOWED_EXTRA_FRONTMATTER: dict[str, type] = {
    "few_shot_count": int,
}

# Title chars that escape directories or denote reserved names.
_TITLE_REJECT_RE = re.compile(r"[/\\\x00]|\.\.|^\.+$|^/")
# Codex round 3 Finding D: cap title length to keep generated paths under
# typical filesystem limits (HFS+/APFS ~255 bytes, ext4 255 bytes, NTFS 255
# UCS-2 chars; Chinese chars at 3 utf-8 bytes each can blow past 255 around
# 80 chars so 200 is a safe cap that still allows long descriptive titles).
_MAX_TITLE_LEN = 200
# Codex round 3 Finding D: reserved internal names that, if used as a page
# title, would collide with vault scaffolding (`.gitkeep` placeholders,
# index files, etc.) and break tooling that scans those names.
_RESERVED_TITLES = {"index", "index.md", ".gitkeep"}


class VoiceSourceViolation(ValueError):
    """voice.md source / author / body violates spec §8.5 red-line."""


class TitleUnsafeError(ValueError):
    """Title contains path separators / parent-traversal / absolute path tokens."""


class FrontmatterExtraKeyError(ValueError):
    """`extra_frontmatter` contains a key not in the allow-list, or wrong type."""


@dataclass
class WriteResult:
    path: Path
    created: bool                # True if newly created inside the lock
    pinned_preserved: list[str]  # field names preserved from prior pinned section
    conflicts: list[str]         # H2 section names that triggered ⚠️ CONFLICT (Codex Finding 8)


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _validate_title(page_type: str, title: str | None) -> None:
    """Reject titles that could escape the wiki/<subtype>/ directory or
    collide with vault internals.

    Rejects (Codex round 3 Finding D):
      - None / empty / whitespace-only (after .strip())
      - path-traversal tokens (`/`, `\\`, `..`, leading `.+`, leading `/`,
        null byte) — via `_TITLE_REJECT_RE`
      - longer than `_MAX_TITLE_LEN` chars (filesystem path overflow)
      - reserved internal names (`index`, `index.md`, `.gitkeep`)
    """
    if page_type in {"persona", "voice"}:
        return  # fixed filename, title unused for path
    if not title or not title.strip():
        raise TitleUnsafeError(
            f"title {title!r} unsafe for page_type {page_type!r}: must not be empty or whitespace-only"
        )
    if len(title) > _MAX_TITLE_LEN:
        raise TitleUnsafeError(
            f"title length {len(title)} exceeds max {_MAX_TITLE_LEN} chars "
            f"for page_type {page_type!r} (Codex round 3 Finding D)"
        )
    if title.strip() in _RESERVED_TITLES:
        raise TitleUnsafeError(
            f"title {title!r} is a reserved internal name "
            f"({sorted(_RESERVED_TITLES)}); choose a different title"
        )
    if _TITLE_REJECT_RE.search(title):
        raise TitleUnsafeError(
            f"title {title!r} unsafe for page_type {page_type!r}: must not contain '/', '\\', '..', or be empty"
        )


def _resolve_path(vault_dir: Path, page_type: str, title: str | None) -> Path:
    if page_type not in _PAGE_TYPE_DIRS:
        raise ValueError(f"unknown page_type {page_type!r}")
    _validate_title(page_type, title)
    spec = _PAGE_TYPE_DIRS[page_type]
    if page_type in {"persona", "voice"}:
        target = Path(vault_dir) / spec[0] / spec[1]
        expected_parent = Path(vault_dir) / spec[0]
    else:
        expected_parent = Path(vault_dir) / spec[0] / spec[1]
        target = expected_parent / f"{title}.md"
    # Defence-in-depth: make sure resolved path stays under expected parent.
    target_resolved = target.resolve(strict=False)
    expected_resolved = expected_parent.resolve(strict=False)
    try:
        target_resolved.relative_to(expected_resolved)
    except ValueError as exc:
        raise TitleUnsafeError(
            f"title {title!r} resolves outside {expected_parent}: {target_resolved}"
        ) from exc
    return target


@contextlib.contextmanager
def _page_lock(target: Path):
    """Per-page exclusive lock via fcntl.flock on a sidecar `.lock` file."""
    lock_path = target.with_suffix(target.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# Codex Finding 14 (round 4): _SECTION_RE matches H2 ONLY. The first line of
# every wiki page is a `# Title` H1 (page title); treating it as a mergeable
# section caused false conflict markers on every re-ingest. All wiki schemas
# (persona / voice / entity / concept / synthesis) use H2 for sections; H1
# is reserved for the page title and lives in the `""` (empty key) preamble.
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H2_RE = _SECTION_RE


def _split_body_sections(body: str) -> dict[str, str]:
    """Split body by `## <name>` headings → {name: section_text_including_heading}.

    Content before the first H2 keys under "" (empty string).
    """
    sections: dict[str, str] = {}
    last_name = ""
    last_pos = 0
    for m in _H2_RE.finditer(body):
        sections[last_name] = sections.get(last_name, "") + body[last_pos:m.start()]
        last_name = m.group(1).strip()
        last_pos = m.start()
    sections[last_name] = sections.get(last_name, "") + body[last_pos:]
    return sections


def _read_existing(path: Path) -> tuple[dict[str, Any] | None, str]:
    """Return (frontmatter, body) or (None, '') if file missing / malformed."""
    if not path.is_file():
        return None, ""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text  # malformed; treat as no frontmatter
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return (fm if isinstance(fm, dict) else None), body


def voice_md_is_valid(vault_dir: Path | str) -> bool:
    """Codex round 1 Finding 5: voice.md presence is necessary but not
    sufficient for default-mode voice transfer. The file must also parse
    as valid yaml frontmatter with `page_type: voice`. Used by query_cmd
    Phase A to decide whether to degrade default mode to literal."""
    vault_dir = Path(vault_dir)
    voice_path = vault_dir / "wiki" / "voice.md"
    if not voice_path.is_file():
        return False
    try:
        text = voice_path.read_text(encoding="utf-8")
    except OSError:
        return False
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return False
    if not isinstance(fm, dict):
        return False
    return fm.get("page_type") == "voice"


def _merge_body(
    old_body: str, new_body: str, pinned_fields: list[str],
) -> tuple[str, list[str], list[str]]:
    """Section-aware merge of new_body into old_body.

    Rules (Codex Findings 7+8):
      - pinned H2: from old (always); if old_body has no such section, that's
        a noop — pin is recorded in frontmatter for the future
      - non-pinned old-only H2: carry forward
      - non-pinned new-only H2: include from new
      - same H2 in both:
          * pinned → use old
          * non-pinned → use new + emit conflict marker for lint

    Returns (merged_body, preserved_pinned_fields, conflict_section_names).
    """
    if not old_body:
        return new_body, [], []

    old_sections = _split_body_sections(old_body)
    new_sections = _split_body_sections(new_body)
    pinned_set = set(pinned_fields)

    preserved: list[str] = []
    conflicts: list[str] = []

    # Determine the merged ordering:
    # 1. Sections in new_body order (from new_sections), with pinned/conflict overrides
    # 2. Sections in old_body that aren't in new_body, appended in old order
    new_order = []
    last_name = ""
    new_order.append(last_name)
    for m in _H2_RE.finditer(new_body):
        last_name = m.group(1).strip()
        new_order.append(last_name)
    seen_in_new = {n for n in new_order}

    old_order = []
    last_name = ""
    old_order.append(last_name)
    for m in _H2_RE.finditer(old_body):
        last_name = m.group(1).strip()
        old_order.append(last_name)

    out_parts: list[str] = []
    seen: set[str] = set()
    for name in new_order:
        if name in seen:
            continue
        seen.add(name)
        if name in pinned_set and name in old_sections:
            out_parts.append(old_sections[name])
            preserved.append(name)
            continue
        if name in old_sections and name in new_sections and name != "":
            # Same H2 in both → new wins, but mark conflict for lint
            new_sec = new_sections[name]
            # Inject the conflict marker right after the H2 line.
            conflict_marker = (
                f"> ⚠️ CONFLICT: section `{name}` rewritten by ingest;"
                " older version available in git history.\n\n"
            )
            # Find the end of the H2 line
            h2_end = new_sec.find("\n")
            if h2_end != -1:
                new_sec = new_sec[: h2_end + 1] + "\n" + conflict_marker + new_sec[h2_end + 1 :]
            out_parts.append(new_sec)
            conflicts.append(name)
            continue
        if name in new_sections:
            out_parts.append(new_sections[name])

    # Append old sections that weren't in new_body (carry-forward,
    # including pinned ones whose H2 the new body omitted).
    for name in old_order:
        if name in seen_in_new:
            continue
        out_parts.append(old_sections.get(name, ""))
        if name in pinned_set:
            preserved.append(name)

    return "".join(out_parts), preserved, conflicts


def _enforce_voice_red_line(
    *,
    sources: list[str],
    source_types_map: dict[str, str] | None,
    target_open_id: str | None,
    voice_evidence: list[dict[str, str]] | None,
) -> None:
    """Voice red-line — code-enforced (spec §8.5 / Codex Findings 1+9).

    For voice writes with non-empty sources, ALL of these are required:
      - target_open_id (str)
      - source_types_map covering every src_id, with allow-listed source_type
      - voice_evidence: list of {src_id, author_open_id, quote}; every entry's
        author_open_id MUST equal target_open_id
    """
    if not sources:
        return  # empty-sources template page is allowed
    if not target_open_id:
        raise VoiceSourceViolation(
            "voice.md write with non-empty sources requires target_open_id"
        )
    if source_types_map is None:
        raise VoiceSourceViolation(
            "voice.md write with non-empty sources requires source_types_map "
            "covering every src_id (spec §8.5)"
        )
    for src in sources:
        stype = source_types_map.get(src)
        if stype is None:
            raise VoiceSourceViolation(
                f"voice.md source {src!r} missing from source_types_map"
            )
        if stype not in _VOICE_ALLOWED_SOURCE_TYPES:
            raise VoiceSourceViolation(
                f"voice.md disallows source {src!r} of type {stype!r}; "
                f"allowed: {sorted(_VOICE_ALLOWED_SOURCE_TYPES)}"
            )

    # Codex Finding 13 (round 4): empty list also rejected — prevents callers
    # from neutralising the red-line by passing []
    if not voice_evidence:
        raise VoiceSourceViolation(
            "voice.md write with non-empty sources requires non-empty "
            "voice_evidence (every quote must be tagged with src_id + "
            "author_open_id; Codex Findings 9+13)"
        )
    for i, ev in enumerate(voice_evidence):
        for key in ("src_id", "author_open_id", "quote"):
            if key not in ev:
                raise VoiceSourceViolation(
                    f"voice_evidence[{i}] missing key {key!r}"
                )
        if ev["src_id"] not in source_types_map:
            raise VoiceSourceViolation(
                f"voice_evidence[{i}] src_id {ev['src_id']!r} not in source_types_map"
            )
        if ev["author_open_id"] != target_open_id:
            raise VoiceSourceViolation(
                f"voice_evidence[{i}] author_open_id {ev['author_open_id']!r} "
                f"!= target_open_id {target_open_id!r}; non-target authors "
                f"cannot be quoted in voice.md (spec §3 决策 18)"
            )


# Codex Finding 10 (round 3): voice body must structurally bind cited quotes
# to evidence entries. Pattern matches markdown list items shaped like:
#   - (src-XXXX): "verbatim quote text"
#   - (src-XXXX, ...): some quote
# Anything inside a `# 场景分段 few-shot` H1 / `## 场景分段 few-shot` H2 (or any
# section whose heading starts with `§`) MUST follow this format and reference
# an evidence entry.
# Few-shot section anchors: H2 or H3 whose heading contains "场景" or "§"
# (e.g. `## 场景分段 few-shot`, `### §1v1 场景`).
_FEWSHOT_SECTION_RE = re.compile(r"^#{2,3}\s+(?:.*?(?:场景|§).*)$", re.MULTILINE)
# Codex Finding 13 (round 4): match prompt formats `- (src):`, `- 范例1(src):`,
# `- (src-NNNN, ts): quote`. Capture the first id-like token inside parens.
_CITED_LIST_RE = re.compile(
    r"^\s*-\s+(?:[^()\n]*?)\(([^)]+?)\)\s*[::]?\s*(.*?)\s*$",
    re.MULTILINE,
)


def _validate_voice_body_quotes(
    body: str,
    *,
    voice_evidence: list[dict[str, str]],
    target_open_id: str,
) -> None:
    """Codex Finding 10: validate that every cited quote in voice body's
    few-shot sections is backed by a voice_evidence entry whose author == target.

    A cited quote is any markdown list item shaped `- (src-XXXX): quote`.
    We allow narrative sections (总体基调 / 句式特征 / 高频口头禅 / 不会出现的表达)
    to contain free text; only sections matching the few-shot pattern (containing
    "场景" or "§") are body-validated. Within those sections, EVERY cited list
    item must reference a src_id that appears in voice_evidence with a quote
    string that exists in evidence.
    """
    # Build (src_id, author, quote) index from evidence
    by_src: dict[str, list[dict[str, str]]] = {}
    for ev in voice_evidence:
        by_src.setdefault(ev["src_id"], []).append(ev)

    # Walk sections; only check ones whose heading triggers _FEWSHOT_SECTION_RE
    section_starts: list[tuple[int, str, bool]] = []  # (offset, name, is_fewshot)
    for m in _SECTION_RE.finditer(body):
        is_fs = bool(_FEWSHOT_SECTION_RE.match(m.group(0)))
        section_starts.append((m.start(), m.group(1).strip(), is_fs))
    # Append sentinel
    section_starts.append((len(body), "", False))

    for i in range(len(section_starts) - 1):
        start, name, is_fs = section_starts[i]
        end = section_starts[i + 1][0]
        if not is_fs:
            continue
        section_text = body[start:end]
        for cm in _CITED_LIST_RE.finditer(section_text):
            cite = cm.group(1).strip().split(",")[0].strip()  # take first id
            quote = cm.group(2).strip().strip('"').strip("“").strip("”")
            evs = by_src.get(cite)
            if not evs:
                raise VoiceSourceViolation(
                    f"voice body cites src {cite!r} (in section {name!r}) "
                    f"but it has no voice_evidence entry"
                )
            # The quoted text must appear in at least one matching evidence
            if not any(quote and quote in ev.get("quote", "") for ev in evs):
                raise VoiceSourceViolation(
                    f"voice body cites src {cite!r} with quote {quote!r} "
                    f"that is not present in voice_evidence (Codex Finding 10)"
                )


def write(
    *,
    vault_dir: Path,
    page_type: str,
    title: str | None,
    sources: list[str],
    confidence: str,
    body: str,
    author_role: str = "ingest",
    needs_review: bool = False,
    pinned_fields: list[str] | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
    source_types_map: dict[str, str] | None = None,
    target_open_id: str | None = None,
    voice_evidence: list[dict[str, str]] | None = None,
) -> WriteResult:
    """Write or update a wiki page atomically. See module docstring for invariants."""
    if confidence not in _VALID_CONFIDENCE:
        raise ValueError(f"confidence must be one of {_VALID_CONFIDENCE}, got {confidence!r}")
    if author_role not in _VALID_AUTHOR_ROLES:
        raise ValueError(f"author_role must be one of {_VALID_AUTHOR_ROLES}, got {author_role!r}")

    # Codex round 1 Finding 1: voice red-line enforcement at AUTHOR layer.
    # Even an empty-sources voice write is forbidden from non-ingest callers.
    # Keeps Phase ask, Phase C review, lint, and any future caller from
    # mutating wiki/voice.md by accident or design.
    if page_type == "voice" and author_role != "ingest":
        raise ValueError(
            f"page_type='voice' may only be written by author_role='ingest', "
            f"got author_role={author_role!r} (spec §8.5 voice red line)"
        )

    # Codex Finding 12 (round 3): extra_frontmatter is an allow-list with type check.
    if extra_frontmatter:
        for k, v in extra_frontmatter.items():
            if k not in _ALLOWED_EXTRA_FRONTMATTER:
                raise FrontmatterExtraKeyError(
                    f"extra_frontmatter key {k!r} not in allow-list "
                    f"{sorted(_ALLOWED_EXTRA_FRONTMATTER)}"
                )
            expected_type = _ALLOWED_EXTRA_FRONTMATTER[k]
            if not isinstance(v, expected_type):
                raise FrontmatterExtraKeyError(
                    f"extra_frontmatter[{k!r}] expected {expected_type.__name__}, "
                    f"got {type(v).__name__}"
                )

    if page_type == "voice":
        _enforce_voice_red_line(
            sources=list(sources),
            source_types_map=source_types_map,
            target_open_id=target_open_id,
            voice_evidence=voice_evidence,
        )
        # Codex Findings 10+13: bind body's cited quotes to evidence. The
        # _enforce_voice_red_line above already guaranteed voice_evidence is
        # non-empty when sources is non-empty, so this branch runs whenever
        # there's anything to validate.
        if sources:
            _validate_voice_body_quotes(
                body, voice_evidence=voice_evidence or [],
                target_open_id=target_open_id or "",
            )

    target = _resolve_path(vault_dir, page_type, title)
    target.parent.mkdir(parents=True, exist_ok=True)

    with _page_lock(target):
        existing_fm, old_body = _read_existing(target)
        created = existing_fm is None

        # Codex round 1 Finding 6: byte-equal idempotency — if the new write
        # would produce the same body as already-on-disk, skip the section-aware
        # merge entirely. Avoids spurious CONFLICT markers on re-ask, re-ingest
        # of unchanged content, and other "I wrote the same thing twice" cases.
        # When ALL of (sources, confidence, needs_review) also match, return
        # WriteResult immediately as a true no-op. When body matches but
        # metadata differs (e.g. apply_review_accept-via-write promotes
        # confidence or clears needs_review per Codex round 3 Finding A), we
        # still write the new metadata but with the existing body verbatim.
        body_byte_equal = existing_fm is not None and old_body == body
        if body_byte_equal:
            existing_sources = list(existing_fm.get("sources", []) or [])
            sources_equivalent = (
                sorted(set(existing_sources) | set(sources)) == sorted(existing_sources)
            )
            confidence_equivalent = (
                existing_fm.get("confidence") == confidence
            )
            needs_review_equivalent = (
                bool(existing_fm.get("needs_review", False)) == bool(needs_review)
            )
            if sources_equivalent and confidence_equivalent and needs_review_equivalent:
                # body, sources, confidence, needs_review all equivalent → no-op.
                return WriteResult(
                    path=target,
                    created=False,
                    pinned_preserved=[],
                    conflicts=[],
                )

        if pinned_fields is None or not created:
            # default carry-forward; on update, always carry-forward existing list
            effective_pinned = list((existing_fm or {}).get("pinned_fields", []) or [])
        else:
            effective_pinned = list(pinned_fields)

        if body_byte_equal:
            # Codex round 1 Finding 6: body byte-equal → skip section-aware
            # merge so we don't emit a spurious CONFLICT marker on identical
            # content. Used by Codex round 3 Finding A flow where caller
            # promotes confidence / clears needs_review without changing body.
            merged_body, preserved, conflicts = old_body, [], []
        else:
            merged_body, preserved, conflicts = _merge_body(old_body, body, effective_pinned)

        existing_sources = list((existing_fm or {}).get("sources", []) or [])
        union_sources = sorted(set(existing_sources) | set(sources))

        fm: dict[str, Any] = {
            "page_type": page_type,
            "title": title,
            "sources": union_sources,
            "confidence": confidence,
            "needs_review": needs_review or bool(conflicts),
            "pinned_fields": effective_pinned,
            "last_modified": _now_iso(),
            "last_modified_by": author_role,
        }
        if page_type == "voice" and voice_evidence is not None:
            fm["voice_evidence"] = voice_evidence
        if extra_frontmatter:
            # Already validated against reserved keys above.
            fm.update(extra_frontmatter)
        if page_type in {"persona", "voice"} and title is None:
            fm.pop("title", None)

        text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + merged_body
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)

    return WriteResult(path=target, created=created, pinned_preserved=preserved, conflicts=conflicts)


def _read_full(path: Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_str). Raises if no frontmatter."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path} missing frontmatter")
    return yaml.safe_load(parts[1]) or {}, parts[2].lstrip("\n")


def pin(*, vault_dir: Path, page_type: str, title: str | None, field: str) -> None:
    """Add a field name to a page's pinned_fields list (idempotent)."""
    target = _resolve_path(vault_dir, page_type, title)
    if not target.is_file():
        raise FileNotFoundError(target)
    with _page_lock(target):
        fm, body = _read_full(target)
        pinned = list(fm.get("pinned_fields", []))
        if field not in pinned:
            pinned.append(field)
        fm["pinned_fields"] = pinned
        fm["last_modified"] = _now_iso()
        fm["last_modified_by"] = "user"
        text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)


def unpin(*, vault_dir: Path, page_type: str, title: str | None, field: str) -> None:
    """Remove a field name from a page's pinned_fields list (idempotent)."""
    target = _resolve_path(vault_dir, page_type, title)
    if not target.is_file():
        raise FileNotFoundError(target)
    with _page_lock(target):
        fm, body = _read_full(target)
        pinned = [f for f in fm.get("pinned_fields", []) if f != field]
        fm["pinned_fields"] = pinned
        fm["last_modified"] = _now_iso()
        fm["last_modified_by"] = "user"
        text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)


# ---------------------------------------------------------------------------
# M4 Task 8 — marker-resolution helpers (Codex Findings 1+2+3+5+6+7+10+12)
# ---------------------------------------------------------------------------


# Marker scan: any of the 3 review markers (CONFLICT / AMBIGUOUS / UNCLEAR).
_ANY_MARKER_RE = re.compile(r"^>\s*⚠️\s*(CONFLICT|AMBIGUOUS|UNCLEAR)\b", re.MULTILINE)


def _normalize_section_body(text: str) -> str:
    """Ensure section body ends with a single trailing newline so concatenation
    with the next H2 doesn't glue (Codex Finding 2)."""
    return text.rstrip("\n") + "\n"


def _recompute_needs_review(body: str, confidence: str, prior: bool) -> bool:
    """Post-resolve: if no ⚠️ markers remain AND confidence is not low,
    flip to False; else keep True (Codex Findings 3 + 5).

    For confidence='low', always return True regardless of prior — low-confidence
    pages MUST be closed by an explicit `apply_review_accept(confidence='medium'+)`
    call. Otherwise resolving the last marker on a low-conf page silently drops
    it from the checklist without user acceptance (Codex round 2 Finding 5).
    """
    if _ANY_MARKER_RE.search(body):
        return True
    if confidence == "low":
        return True   # Codex Finding 5: low-conf must be explicitly accepted
    return False


def _extract_non_conflict_markers_from_section(section_text: str) -> list[str]:
    """Find AMBIGUOUS / UNCLEAR marker BLOCKS inside an old H2 section so we
    can preserve them when resolve_conflict overwrites the section body.

    Codex round 3 Finding 10: a marker block is the marker line PLUS any
    immediately-following continuation `>` quote lines (the explanation /
    candidates / evidence the LLM wrote next to the marker). Preserving only
    the marker line silently drops that context.
    """
    out: list[str] = []
    lines = section_text.splitlines()
    i = 0
    while i < len(lines):
        if re.match(r"^>\s*⚠️\s*(AMBIGUOUS|UNCLEAR)\b", lines[i]):
            block = [lines[i]]
            j = i + 1
            # Continuation: any line still part of the same blockquote (`> ...`,
            # `>` blank, or empty `>`) — until we hit a non-blockquote line or
            # another ⚠️ marker block.
            while j < len(lines):
                line = lines[j]
                if re.match(r"^>\s*⚠️\s*(CONFLICT|AMBIGUOUS|UNCLEAR)\b", line):
                    break
                if line.startswith(">"):
                    block.append(line)
                    j += 1
                    continue
                break
            out.append("\n".join(block))
            i = j
            continue
        i += 1
    return out


def resolve_conflict(
    *,
    vault_dir: Path,
    page_type: str,
    title: str | None,
    section_name: str,
    accepted_body: str,
    decided_by_user: bool = True,
) -> WriteResult:
    """Replace `## <section_name>` body with `accepted_body`; drop CONFLICT
    markers within that section but PRESERVE any AMBIGUOUS / UNCLEAR markers
    that were also in that section (Codex Finding 6). Recompute needs_review
    across the whole page.

    Note: this function is also used for the [B] / [D] paths of Phase C
    needs_review edits (overwrite a section with a user-confirmed body) — see
    `references/prompt-review.md`. The section need not currently contain a
    CONFLICT marker; the function name reflects its primary use case."""
    target = _resolve_path(vault_dir, page_type, title)
    if not target.is_file():
        raise FileNotFoundError(target)

    with _page_lock(target):
        existing_fm, old_body = _read_existing(target)
        if existing_fm is None:
            raise ValueError(f"{target} has no frontmatter")

        sections = _split_body_sections(old_body)
        if section_name not in sections:
            raise ValueError(
                f"section {section_name!r} not found in page {target}; "
                f"available sections: {sorted(s for s in sections if s)}"
            )

        # Codex Finding 6: extract non-CONFLICT markers (AMBIGUOUS / UNCLEAR)
        # from the old section so we can re-attach them to the new body.
        preserved_markers = _extract_non_conflict_markers_from_section(sections[section_name])

        # Build new section: H2 + normalized accepted_body + preserved marker
        # blocks (each block already includes its multi-line context).
        normalized = _normalize_section_body(accepted_body)
        if preserved_markers:
            # Each block already has its trailing newline-less form; join with
            # blank-line separators so blockquotes render correctly.
            preserved_block = "\n\n".join(preserved_markers) + "\n"
            new_section = f"## {section_name}\n{normalized}\n{preserved_block}"
        else:
            new_section = f"## {section_name}\n{normalized}"
        sections[section_name] = new_section

        ordered_names: list[str] = [""]
        for m in _SECTION_RE.finditer(old_body):
            ordered_names.append(m.group(1).strip())
        new_body = "".join(sections.get(n, "") for n in ordered_names)

        existing_fm["needs_review"] = _recompute_needs_review(
            new_body,
            existing_fm.get("confidence", "low"),
            existing_fm.get("needs_review", False),
        )
        existing_fm["last_modified"] = _now_iso()
        existing_fm["last_modified_by"] = "user" if decided_by_user else "review"

        text = "---\n" + yaml.safe_dump(existing_fm, allow_unicode=True, sort_keys=False) + "---\n\n" + new_body
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)

    return WriteResult(path=target, created=False, pinned_preserved=[], conflicts=[])


def _resolve_inline_marker(
    *,
    vault_dir: Path,
    page_type: str,
    title: str | None,
    marker_kind: str,           # "AMBIGUOUS" | "UNCLEAR"
    marker_text_substring: str,
    replacement: str,
    decided_by_user: bool,
) -> WriteResult:
    """Find a `> ⚠️ <KIND>: <line>` whose text contains `marker_text_substring`,
    remove that line. If `replacement` non-empty, insert it on its own line where
    the marker was. Recompute needs_review."""
    target = _resolve_path(vault_dir, page_type, title)
    if not target.is_file():
        raise FileNotFoundError(target)

    with _page_lock(target):
        existing_fm, old_body = _read_existing(target)
        if existing_fm is None:
            raise ValueError(f"{target} has no frontmatter")

        line_re = re.compile(
            rf"^>\s*⚠️\s*{re.escape(marker_kind)}[::]\s*(.*)$", re.MULTILINE,
        )
        matches = [m for m in line_re.finditer(old_body) if marker_text_substring in m.group(1)]
        # Codex Finding 7: enforce uniqueness — one user decision = one marker.
        if not matches:
            raise ValueError(
                f"{marker_kind} marker matching {marker_text_substring!r} not found in {target}"
            )
        if len(matches) > 1:
            raise ValueError(
                f"{marker_kind} marker substring {marker_text_substring!r} matches "
                f"{len(matches)} markers in {target}; pass a longer / more unique substring "
                "so exactly one marker is targeted (Codex Finding 7)"
            )

        # Codex round 4 Finding 12: extend the deletion span to cover any
        # multi-line `> ` continuation context immediately after the marker
        # (candidates / evidence / quoted excerpts the LLM may have written).
        # Otherwise resolving the marker leaves stale context behind.
        m = matches[0]
        block_start = m.start()
        block_end = m.end()
        # Walk lines after the marker; consume contiguous `>`-prefixed lines
        # until we hit a non-blockquote line OR another ⚠️ marker.
        cursor = block_end
        while cursor < len(old_body):
            # Skip leading newline of next line
            if old_body[cursor] != "\n":
                break
            line_start_next = cursor + 1
            line_end_next = old_body.find("\n", line_start_next)
            if line_end_next == -1:
                line_end_next = len(old_body)
            line = old_body[line_start_next:line_end_next]
            if not line.startswith(">"):
                break
            if re.match(r"^>\s*⚠️\s*(CONFLICT|AMBIGUOUS|UNCLEAR)\b", line):
                break
            cursor = line_end_next
        block_end = cursor
        # Also consume ONE trailing newline after the block (collapse blank
        # line that typically separated marker from next content).
        if block_end < len(old_body) and old_body[block_end] == "\n":
            block_end += 1

        sub = f"{replacement.rstrip()}\n" if replacement.strip() else ""
        new_body = old_body[:block_start] + sub + old_body[block_end:]

        existing_fm["needs_review"] = _recompute_needs_review(
            new_body,
            existing_fm.get("confidence", "low"),
            existing_fm.get("needs_review", False),
        )
        existing_fm["last_modified"] = _now_iso()
        existing_fm["last_modified_by"] = "user" if decided_by_user else "review"

        text = "---\n" + yaml.safe_dump(existing_fm, allow_unicode=True, sort_keys=False) + "---\n\n" + new_body
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)

    return WriteResult(path=target, created=False, pinned_preserved=[], conflicts=[])


def resolve_ambiguity(
    *,
    vault_dir: Path,
    page_type: str,
    title: str | None,
    marker_text_substring: str,
    replacement: str,
    decided_by_user: bool = True,
) -> WriteResult:
    """Resolve a `> ⚠️ AMBIGUOUS: ...` marker line in the page (Codex Finding 1)."""
    return _resolve_inline_marker(
        vault_dir=vault_dir, page_type=page_type, title=title,
        marker_kind="AMBIGUOUS",
        marker_text_substring=marker_text_substring,
        replacement=replacement,
        decided_by_user=decided_by_user,
    )


def resolve_unclear(
    *,
    vault_dir: Path,
    page_type: str,
    title: str | None,
    marker_text_substring: str,
    replacement: str,
    decided_by_user: bool = True,
) -> WriteResult:
    """Resolve a `> ⚠️ UNCLEAR: ...` marker line in the page (Codex Finding 1)."""
    return _resolve_inline_marker(
        vault_dir=vault_dir, page_type=page_type, title=title,
        marker_kind="UNCLEAR",
        marker_text_substring=marker_text_substring,
        replacement=replacement,
        decided_by_user=decided_by_user,
    )


# ---------------------------------------------------------------------------
# M4 Task 9 — apply_review_accept (Phase C dialogue option [A] 接受)
# ---------------------------------------------------------------------------


def forget_rewrite(
    *,
    vault_dir: Path,
    page_type: str,
    title: str | None,
    sources: list[str],
    confidence: str,
    body: str,
    needs_review: bool = True,
) -> WriteResult:
    """Forget Level 2 rewrite — replaces (not unions) sources, clears
    forget_dirty marker. Bypasses M3 ingest sources-union and M5 byte-equal
    idempotency. Voice page is rejected (spec §8.5 M5 author guard).

    Codex round 1 Findings 2, 3, 7."""
    if page_type == "voice":
        raise ValueError(
            "page_type='voice' rejected by forget_rewrite — voice page is "
            "regenerated only by ingest with author_role='ingest' "
            "(spec §8.5 voice red line)"
        )
    if confidence not in _VALID_CONFIDENCE:
        raise ValueError(f"confidence must be one of {_VALID_CONFIDENCE}, got {confidence!r}")

    target = _resolve_path(vault_dir, page_type, title)
    target.parent.mkdir(parents=True, exist_ok=True)

    with _page_lock(target):
        existing_fm, _old_body = _read_existing(target)
        # carry-forward pinned_fields (not sources — that's the whole point)
        pinned = list((existing_fm or {}).get("pinned_fields", []) or [])

        fm: dict[str, Any] = {
            "page_type": page_type,
            "title": title,
            "sources": list(sources),   # REPLACE not union (Codex Finding 3)
            "confidence": confidence,
            "needs_review": needs_review,
            "pinned_fields": pinned,
            "last_modified": _now_iso(),
            "last_modified_by": "user",
        }
        if page_type in {"persona", "voice"} and title is None:
            fm.pop("title", None)
        # Codex round 2 Finding F: preserve M3 allow-listed extra
        # frontmatter keys (voice_evidence, etc.) — do NOT silently drop
        # them. Explicitly drop only sources/forget_dirty/the fields we
        # rebuild from args.
        if existing_fm:
            _MANAGED = {
                "page_type", "title", "sources", "confidence", "needs_review",
                "pinned_fields", "last_modified", "last_modified_by",
                "forget_dirty",  # explicitly cleared by rewrite
            }
            for k, v in existing_fm.items():
                if k not in _MANAGED and k in _ALLOWED_EXTRA_FRONTMATTER:
                    fm[k] = v

        text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)

    return WriteResult(
        path=target, created=False,
        pinned_preserved=pinned, conflicts=[],
    )


def apply_review_accept(
    *,
    vault_dir: Path,
    page_type: str,
    title: str | None,
    confidence: str | None = None,
    pin_fields: list[str] | None = None,
) -> None:
    """Frontmatter-only update: needs_review → false; optionally promote
    confidence + pin fields. Used by Phase C [A] 接受."""
    if confidence is not None and confidence not in _VALID_CONFIDENCE:
        raise ValueError(f"confidence must be one of {_VALID_CONFIDENCE}, got {confidence!r}")
    target = _resolve_path(vault_dir, page_type, title)
    if not target.is_file():
        raise FileNotFoundError(target)

    with _page_lock(target):
        existing_fm, old_body = _read_existing(target)
        if existing_fm is None:
            raise ValueError(f"{target} has no frontmatter")

        existing_fm["needs_review"] = False
        if confidence is not None:
            existing_fm["confidence"] = confidence
        if pin_fields:
            current = list(existing_fm.get("pinned_fields", []) or [])
            for f in pin_fields:
                if f not in current:
                    current.append(f)
            existing_fm["pinned_fields"] = current
        existing_fm["last_modified"] = _now_iso()
        existing_fm["last_modified_by"] = "user"

        text = "---\n" + yaml.safe_dump(existing_fm, allow_unicode=True, sort_keys=False) + "---\n\n" + old_body
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)
