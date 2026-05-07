# scripts/clonemate/clone_cmd.py
"""clone_cmd — top-level orchestrator for `clonemate clone <handle>`.

Flow (spec §6.1 steps 1-3):
  1. resolve handle → Candidate(s); if multiple, picker callback chooses one
     (M2 picker: pick first if non-interactive, else prompt via stdin)
  2. derive ASCII slug:  explicit --slug  >  ASCII slugified display_name
                       >  email local-part   >  raise SlugRequiredError
  3. abort if vault dir exists
  4. vault.init
  5. fetch_sources.run

M2 explicitly does NOT write any wiki content — only raw + _clone.yaml.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from clonemate import fetch_sources, resolve, vault


class VaultExistsError(RuntimeError):
    """Raised when target vault dir already exists (use sync instead)."""


class SlugRequiredError(RuntimeError):
    """Raised when no ASCII-friendly slug can be derived; caller must pass --slug."""


_EMAIL_LOCAL_RE = re.compile(r"^([A-Za-z0-9._-]+)@")


def _slugify(name: str) -> str:
    """ASCII-only slug. Returns '' when input has no ASCII alphanumerics.

    Chinese / non-Latin scripts produce '' (NFKD does not transliterate Chinese);
    callers must fall back to email local-part or an explicit --slug.
    """
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    norm = "".join(ch.lower() if ch.isalnum() else "-" for ch in norm).strip("-")
    # Empty when input had no ASCII alphanumerics — let caller fall back.
    return norm


def _email_local_part(email: str | None) -> str:
    if not email:
        return ""
    m = _EMAIL_LOCAL_RE.match(email)
    if not m:
        return ""
    return _slugify(m.group(1))


def _derive_slug(*, override: str | None, display_name: str, email: str | None, handle: str) -> str:
    """Slug derivation chain: --slug override → display_name → email local-part → handle (if it has ASCII).

    Returns '' when none of the sources yield ASCII letters; caller raises SlugRequiredError.
    """
    if override:
        return _slugify(override)
    return (
        _slugify(display_name)
        or _email_local_part(email)
        or _slugify(handle)
    )


def clone(
    *,
    root: Path,
    handle: str,
    my_open_id: str,
    profile: str,
    since: str,
    slug: str | None = None,
    picker=None,
) -> fetch_sources.FetchReport:
    candidates = resolve.resolve_handle(handle, profile=profile)
    if len(candidates) > 1:
        if picker is None:
            chosen = candidates[0]   # M2 default: pick first non-interactively
        else:
            chosen = picker(candidates)
    else:
        chosen = candidates[0]

    derived_slug = _derive_slug(
        override=slug, display_name=chosen.display_name, email=chosen.email, handle=handle,
    )
    if not derived_slug:
        raise SlugRequiredError(
            f"Cannot derive ASCII slug from display_name={chosen.display_name!r} / "
            f"email={chosen.email!r} / handle={handle!r}; pass --slug explicitly."
        )

    vault_dir = root / derived_slug
    if vault_dir.exists():
        raise VaultExistsError(f"vault {vault_dir} already exists; use sync instead")

    vault.init(
        vault_dir=vault_dir, slug=derived_slug,
        open_id=chosen.open_id, app_id=chosen.app_id,
        display_name=chosen.display_name, profile=profile,
        aliases=[chosen.display_name] + ([chosen.email] if chosen.email else []),
    )
    return fetch_sources.run(vault_dir=vault_dir, my_open_id=my_open_id, since_str=since)
