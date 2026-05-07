"""Tests for cross_vault — used by forget Level 1 to scrub references."""
from __future__ import annotations

from pathlib import Path

import yaml
from clonemate import cross_vault


def _vault(root: Path, slug: str) -> Path:
    vault = root / slug
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": slug,
                "identity": {
                    "open_id": "ou_xxxxxxxxxxxxxxxx",
                    "app_id": "cli_xxxxxxxxxxxxxxxx",
                },
                "display_name": slug,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return vault


def test_scrub_replaces_slug_references_in_other_vaults(tmp_path: Path) -> None:
    """A synthesis in lisi's vault references zhangsan/wiki/persona.md;
    after scrubbing zhangsan, the reference is replaced with placeholder."""
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    lisi = _vault(root, "lisi")
    syn = lisi / "wiki" / "syntheses" / "对比.md"
    syn.write_text(
        "---\npage_type: synthesis\ntitle: 对比\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n---\n\n"
        "# 对比\n\n"
        "## 综述\n参考 zhangsan/wiki/persona.md 中提到的方法\n",
        encoding="utf-8",
    )
    # Now forget zhangsan — scrub the reference from lisi's synthesis
    count = cross_vault.scrub_slug_from_syntheses(root, "zhangsan")
    assert count == 1
    text = syn.read_text(encoding="utf-8")
    assert "zhangsan/wiki" not in text
    assert "(reference forgotten)" in text


def test_scrub_returns_zero_when_no_references(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    lisi = _vault(root, "lisi")
    syn = lisi / "wiki" / "syntheses" / "x.md"
    syn.write_text(
        "---\npage_type: synthesis\ntitle: x\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n---\n\n# x\n",
        encoding="utf-8",
    )
    count = cross_vault.scrub_slug_from_syntheses(root, "zhangsan")
    assert count == 0
    # Synthesis untouched
    assert "x" in syn.read_text(encoding="utf-8")


def test_scrub_cleans_frontmatter_cross_vault_refs_list(tmp_path: Path) -> None:
    """Codex round 4 Issue-I (HIGH): frontmatter cross_vault_refs list must
    be parsed structurally, with the forgotten slug removed."""
    root = tmp_path / "root"
    _vault(root, "zhangsan")
    lisi = _vault(root, "lisi")
    syn = lisi / "wiki" / "syntheses" / "comparison.md"
    syn.write_text(
        "---\npage_type: synthesis\ntitle: comparison\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n"
        "cross_vault_refs: [zhangsan, wangwu]\n---\n\n"
        "# comparison\n\n## summary\nbody only\n",
        encoding="utf-8",
    )
    count = cross_vault.scrub_slug_from_syntheses(root, "zhangsan")
    assert count == 1
    fm = yaml.safe_load(syn.read_text(encoding="utf-8").split("---")[1])
    assert fm["cross_vault_refs"] == ["wangwu"]
    assert "zhangsan" not in fm["cross_vault_refs"]


def test_scrub_skips_the_being_forgotten_vault_itself(tmp_path: Path) -> None:
    """If zhangsan is being forgotten and zhangsan's vault still exists
    (mid-rm-rf), don't scrub its own syntheses (they're about to be deleted)."""
    root = tmp_path / "root"
    zhangsan = _vault(root, "zhangsan")
    syn = zhangsan / "wiki" / "syntheses" / "self.md"
    syn.write_text(
        "---\npage_type: synthesis\ntitle: self\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n---\n\n"
        "# self\nzhangsan/wiki/persona.md is me\n",
        encoding="utf-8",
    )
    count = cross_vault.scrub_slug_from_syntheses(root, "zhangsan")
    assert count == 0  # self-references inside the forgotten vault are skipped
