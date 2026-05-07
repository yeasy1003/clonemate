from __future__ import annotations

from pathlib import Path

import yaml
from clonemate.raw_writer import RawCandidate, RawWriter


def test_write_creates_raw_file(tmp_path: Path) -> None:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    writer = RawWriter(vault)
    candidate = RawCandidate(
        source_type="contact",
        relative_path="contact/profile.md",
        hash_input="user-id ou_xxxxxxxxxxxxxxxx | dept Y",
        frontmatter={"source_type": "contact", "fetched_at": "2026-04-29T15:00:00+08:00"},
        content="# 张三\n\n部门:Y 团队\n",
    )
    result = writer.write(candidate)

    assert result.written is True
    assert result.skipped is False
    # Path is rewritten to include 8-char hash prefix to preserve raw immutability.
    assert result.path.exists()
    assert result.path.parent == vault / "raw" / "contact"
    assert result.path.stem.startswith("profile-")     # profile-<hash_prefix>
    assert len(result.path.stem) == len("profile-") + 8

    text = result.path.read_text(encoding="utf-8")
    # frontmatter must contain src_id and content_hash assigned by writer
    fm_start = text.index("---") + 3
    fm_end = text.index("---", fm_start)
    fm = yaml.safe_load(text[fm_start:fm_end])
    assert fm["src_id"].startswith("src-")
    assert fm["content_hash"].startswith("sha256:")
    assert "# 张三" in text


def test_write_skips_dup_hash(tmp_path: Path) -> None:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    writer = RawWriter(vault)
    cand = RawCandidate(
        source_type="contact",
        relative_path="contact/profile.md",
        hash_input="same input",
        frontmatter={"x": 1},
        content="body",
    )
    r1 = writer.write(cand)
    r2 = writer.write(cand)
    assert r1.written is True and r2.written is False
    assert r2.skipped is True


def test_src_id_increments(tmp_path: Path) -> None:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    writer = RawWriter(vault)
    r1 = writer.write(RawCandidate("a", "a/1.md", "in1", {}, "body1"))
    r2 = writer.write(RawCandidate("a", "a/2.md", "in2", {}, "body2"))
    r3 = writer.write(RawCandidate("b", "b/1.md", "in3", {}, "body3"))
    assert r1.src_id == "src-0001"
    assert r2.src_id == "src-0002"
    assert r3.src_id == "src-0003"


def test_hashes_isolated_per_source_type(tmp_path: Path) -> None:
    """Two source_types with the same hash_input should both write — hashes are tracked per source_type."""
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    writer = RawWriter(vault)
    r1 = writer.write(RawCandidate("contact", "contact/profile.md", "X", {}, "c1"))
    r2 = writer.write(RawCandidate("docs",    "docs/d.md",         "X", {}, "c2"))
    assert r1.written is True
    assert r2.written is True


def test_frontmatter_preserves_caller_keys(tmp_path: Path) -> None:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    writer = RawWriter(vault)
    result = writer.write(RawCandidate(
        source_type="im_1v1",
        relative_path="im_1v1/oc_x/2026-04.md",
        hash_input="conv",
        frontmatter={
            "participants": ["ou_xxxxxxxxxxxxxxxx", "ou_xxxxxxxxxxxxxxxx"],
            "window": {"start": "2026-04-15T10:00:00+08:00"},
        },
        content="> 张三 (10:01): hi\n",
    ))
    # Path is rewritten with hash suffix; the exact name is hash-derived.
    assert result.path.parent == vault / "raw" / "im_1v1" / "oc_x"
    assert result.path.stem.startswith("2026-04-")
    assert len(result.path.stem) == len("2026-04-") + 8

    text = result.path.read_text(encoding="utf-8")
    assert "participants:" in text
    assert "window:" in text
    assert "src_id: src-0001" in text
    assert "content_hash: sha256:" in text


def test_two_syncs_same_partition_do_not_overwrite(tmp_path: Path) -> None:
    """spec §3.1 raw 不可变 — second sync of the same logical partition with
    new content (e.g. additional messages in the same month) MUST NOT overwrite
    the first sync's raw file. Both files coexist on disk under different
    hash-suffixed names. (regression for Codex Finding 2)"""
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    writer = RawWriter(vault)

    # First sync: 2 messages in April 2026.
    first = writer.write(RawCandidate(
        source_type="im_1v1",
        relative_path="im_1v1/oc_x/2026-04.md",
        hash_input="msg1\nmsg2",
        frontmatter={"chat_id": "oc_x", "messages": [{"id": "m1"}, {"id": "m2"}]},
        content="> author=ou_x: msg1\n> author=ou_x: msg2\n",
    ))

    # Second sync: 3 more messages in the same April -> different hash_input.
    second = writer.write(RawCandidate(
        source_type="im_1v1",
        relative_path="im_1v1/oc_x/2026-04.md",
        hash_input="msg3\nmsg4\nmsg5",
        frontmatter={"chat_id": "oc_x", "messages": [{"id": "m3"}, {"id": "m4"}, {"id": "m5"}]},
        content="> author=ou_x: msg3\n> author=ou_x: msg4\n> author=ou_x: msg5\n",
    ))

    assert first.written is True and second.written is True
    assert first.path != second.path                    # different files
    assert first.path.exists() and second.path.exists() # both preserved
    # Both share the same parent directory and 2026-04- prefix.
    assert first.path.parent == second.path.parent
    assert first.path.stem.startswith("2026-04-")
    assert second.path.stem.startswith("2026-04-")
    # Disk now has two distinct raw files for the same logical partition.
    files_in_april = sorted((vault / "raw" / "im_1v1" / "oc_x").glob("2026-04-*.md"))
    assert len(files_in_april) == 2
