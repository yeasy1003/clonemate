"""Tests for index_upsert.py."""
from __future__ import annotations

from pathlib import Path

from clonemate import index_upsert, merge_note


def _vault_with_wiki(tmp_path: Path) -> Path:
    v = tmp_path / "zhangsan"
    (v / "wiki" / "entities").mkdir(parents=True)
    (v / "wiki" / "concepts").mkdir(parents=True)
    (v / "wiki" / "syntheses").mkdir(parents=True)
    (v / "wiki" / "sources").mkdir(parents=True)
    return v


def test_scan_returns_pages_grouped_by_type(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-0001"], confidence="high",
        body="# XX 项目\n", author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="concept", title="技术选型偏好",
        sources=["src-0007"], confidence="medium",
        body="# 选型\n", author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=[], confidence="low",
        body="# 张三\n", author_role="ingest", needs_review=True,
    )

    summary = index_upsert.scan_wiki(vault)
    titles = {p.title for p in summary.pages}
    assert "XX 项目" in titles
    assert "技术选型偏好" in titles
    by_type = {p.page_type for p in summary.pages}
    assert by_type == {"entity", "concept", "persona"}
    assert summary.needs_review_count == 1
    assert summary.conflict_count == 0


def test_rebuild_writes_index_with_buckets(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-0001"], confidence="high",
        body="# XX 项目\n", author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=[], confidence="low",
        body="# 张三\n", author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="voice", title=None,
        sources=[], confidence="low",
        body="## 总体基调\n", author_role="ingest",
    )

    index_upsert.rebuild(vault, display_name="张三")
    index = (vault / "index.md").read_text(encoding="utf-8")
    # Has all required buckets
    for h in ["待裁决", "Persona", "Entities", "Concepts", "Syntheses", "Sources"]:
        assert h in index
    assert "XX 项目" in index
    assert "wiki/persona.md" in index
    assert "wiki/voice.md" in index
    # No needs_review / conflict (counts = 0)
    assert "待复核:0" in index
    assert "冲突:0" in index


def test_update_page_adjusts_counts_only(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="A",
        sources=["src-0001"], confidence="high",
        body="# A\n", author_role="ingest",
    )
    index_upsert.rebuild(vault, display_name="张三")
    before = (vault / "index.md").read_text(encoding="utf-8")
    assert "wiki/entities/A.md" in before

    # Add another entity then update
    merge_note.write(
        vault_dir=vault, page_type="entity", title="B",
        sources=["src-0002"], confidence="medium",
        body="# B\n", author_role="ingest",
    )
    index_upsert.update_page(vault, page_path=vault / "wiki" / "entities" / "B.md", display_name="张三")
    after = (vault / "index.md").read_text(encoding="utf-8")
    assert "wiki/entities/A.md" in after
    assert "wiki/entities/B.md" in after


def test_cli_rebuild(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=[], confidence="medium", body="# X\n", author_role="ingest",
    )
    rc = index_upsert.main(["--vault-dir", str(vault), "--display-name", "张三"])
    assert rc == 0
    assert (vault / "index.md").is_file()


def test_cli_missing_vault_returns_2(tmp_path: Path) -> None:
    rc = index_upsert.main(["--vault-dir", str(tmp_path / "ghost"), "--display-name", "X"])
    assert rc == 2


def test_rebuild_appends_to_log_when_log_path_given(tmp_path: Path) -> None:
    vault = _vault_with_wiki(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=[], confidence="medium", body="# X\n", author_role="ingest",
    )
    log = vault / "log.md"
    index_upsert.rebuild(vault, display_name="张三", log_path=log)
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "index_rebuild" in text
