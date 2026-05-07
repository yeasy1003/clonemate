"""Cross-vault helpers — used by forget Level 1 to scrub references in
other vaults' synthesis pages when one vault is forgotten."""
from __future__ import annotations

import re
from pathlib import Path

_PLACEHOLDER = "(reference forgotten)"


def _build_slug_pattern(slug: str) -> re.Pattern[str]:
    """Codex round 1 Finding 8: boundary-safe regex so a short slug like
    `li` doesn't match `ali/wiki`. The slug must be preceded by a non-word
    char (or start-of-string) and the path component must be `<slug>/wiki`."""
    return re.compile(rf"(?:^|(?<=[^A-Za-z0-9_])){re.escape(slug)}/wiki")


def _scrub_frontmatter_cross_vault_refs(text: str, slug: str) -> tuple[str, bool]:
    """Codex round 4 Issue-I (HIGH): if the synthesis frontmatter has a
    `cross_vault_refs:` list containing `slug`, parse it structurally,
    remove the entry, and serialize back. Returns (new_text, changed).
    Falls back to identity if the frontmatter doesn't have that key or
    can't be parsed."""
    import yaml as _yaml
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text, False
    try:
        fm = _yaml.safe_load(parts[1]) or {}
    except _yaml.YAMLError:
        return text, False
    if not isinstance(fm, dict):
        return text, False
    refs = fm.get("cross_vault_refs")
    if not isinstance(refs, list) or slug not in refs:
        return text, False
    fm["cross_vault_refs"] = [r for r in refs if r != slug]
    new_fm_text = _yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
    new_text = "---\n" + new_fm_text + "---" + parts[2]
    return new_text, True


def scrub_slug_from_syntheses(root: Path | str, slug: str) -> int:
    """For every vault under `root` EXCEPT the one named `slug`, scan its
    `wiki/syntheses/*.md` for:

      1. Body references like `<slug>/wiki/...` → replace with
         `(reference forgotten)` (Codex round 1 Finding 8: boundary-safe regex).
      2. Frontmatter `cross_vault_refs:` list entries equal to slug
         (Codex round 4 Issue-I HIGH: structured parse + remove).

    Returns the number of pages touched. Spec §6.5 Level 1 step 3.
    """
    from clonemate.vault import iter_vaults_under_root
    root = Path(root)
    pattern = _build_slug_pattern(slug)
    touched = 0
    for vault in iter_vaults_under_root(root):
        if vault.name == slug:
            continue  # skip the vault being forgotten
        syn_dir = vault / "wiki" / "syntheses"
        if not syn_dir.is_dir():
            continue
        for syn_file in sorted(syn_dir.glob("*.md")):
            try:
                text = syn_file.read_text(encoding="utf-8")
            except OSError:
                continue
            # 1. Frontmatter list cleanup (structured)
            text_after_fm, _fm_changed = _scrub_frontmatter_cross_vault_refs(text, slug)
            # 2. Body regex replacement
            new_text = pattern.sub(_PLACEHOLDER, text_after_fm)
            if new_text == text:
                continue
            syn_file.write_text(new_text, encoding="utf-8")
            touched += 1
    return touched
