"""Unit tests for lint_cmd — Phase lint orchestration."""
from __future__ import annotations

import datetime as _dt
import subprocess
from pathlib import Path

import yaml
from clonemate import lint_cmd, merge_note


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan",
        "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx",
                     "app_id": "cli_xxxxxxxxxxxxxxxx"},
        "display_name": "张三",
        "profile": "claude-code",
    }, allow_unicode=True), encoding="utf-8")
    return vault


def test_lint_report_dataclass_fields() -> None:
    rpt = lint_cmd.LintReport()
    assert rpt.orphan_pages == []
    assert rpt.missing_sources_pages == []
    assert rpt.dead_refs == []
    assert rpt.stale_pages == []
    assert rpt.is_empty() is True
    assert rpt.total_findings() == 0


def test_lint_report_total_findings_counts_all() -> None:
    rpt = lint_cmd.LintReport()
    rpt.orphan_pages = [lint_cmd.OrphanPage(page_relpath="wiki/x.md")]
    rpt.missing_sources_pages = [lint_cmd.MissingSourcesPage(page_relpath="wiki/y.md")]
    rpt.dead_refs = [
        lint_cmd.DeadRef(page_relpath="wiki/z.md", missing_src_id="src-9999"),
    ]
    rpt.stale_pages = [
        lint_cmd.StalePage(page_relpath="wiki/a.md", days_since=120),
    ]
    assert rpt.total_findings() == 4
    assert rpt.is_empty() is False


def test_scan_orphan_pages_finds_pages_missing_from_index(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # index.md mentions only XX 项目, not YY 项目
    (vault / "index.md").write_text(
        "# 索引\n\n## 🏷️ Entities\n- [XX 项目](wiki/entities/XX 项目.md)\n",
        encoding="utf-8",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-1"], confidence="medium",
        body="# XX 项目\n", author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="YY 项目",
        sources=["src-2"], confidence="medium",
        body="# YY 项目\n", author_role="ingest",
    )
    out = lint_cmd.scan_orphan_pages(vault)
    relpaths = [o.page_relpath for o in out]
    assert "wiki/entities/YY 项目.md" in relpaths
    # Listed page is not orphan
    assert "wiki/entities/XX 项目.md" not in relpaths
    # voice / persona never count as orphans even when not in index
    assert "wiki/voice.md" not in relpaths
    assert "wiki/persona.md" not in relpaths


def test_scan_orphan_pages_empty_when_index_missing(tmp_path: Path) -> None:
    """No index.md → no orphan analysis possible (return empty, not crash)."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="medium",
        body="# X\n", author_role="ingest",
    )
    out = lint_cmd.scan_orphan_pages(vault)
    assert out == []


def test_scan_missing_sources_pages_finds_empty_sources(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # write a page directly with empty sources frontmatter
    page = vault / "wiki" / "entities" / "broken.md"
    page.write_text(
        "---\npage_type: entity\ntitle: broken\nsources: []\n"
        "confidence: low\nneeds_review: true\n---\n\n# broken\n",
        encoding="utf-8",
    )
    out = lint_cmd.scan_missing_sources_pages(vault)
    assert any(p.page_relpath == "wiki/entities/broken.md" for p in out)


def test_scan_missing_sources_pages_finds_missing_key(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    page = vault / "wiki" / "entities" / "noKey.md"
    page.write_text(
        "---\npage_type: entity\ntitle: noKey\n"
        "confidence: low\nneeds_review: true\n---\n\n# noKey\n",
        encoding="utf-8",
    )
    out = lint_cmd.scan_missing_sources_pages(vault)
    assert any(p.page_relpath == "wiki/entities/noKey.md" for p in out)


def test_scan_missing_sources_pages_skips_voice_with_no_sources(tmp_path: Path) -> None:
    """Voice page may legitimately have empty sources during template phase."""
    vault = _vault(tmp_path)
    (vault / "wiki" / "voice.md").write_text(
        "---\npage_type: voice\nsources: []\nfew_shot_count: 0\n"
        "confidence: low\n---\n\n# template\n",
        encoding="utf-8",
    )
    out = lint_cmd.scan_missing_sources_pages(vault)
    assert all("voice" not in p.page_relpath for p in out)


def test_scan_dead_refs_finds_missing_raw_files(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # Write a wiki page that claims sources [src-0001, src-9999]
    page = vault / "wiki" / "entities" / "X.md"
    page.write_text(
        "---\npage_type: entity\ntitle: X\nsources: [src-0001, src-9999]\n"
        "confidence: medium\nneeds_review: false\n---\n\n# X\n",
        encoding="utf-8",
    )
    # Only src-0001.md exists in raw
    (vault / "raw" / "im_1v1").mkdir()
    (vault / "raw" / "im_1v1" / "src-0001.md").write_text(
        "---\nsrc_id: src-0001\n---\n# raw\n", encoding="utf-8",
    )
    out = lint_cmd.scan_dead_refs(vault)
    refs = [(d.page_relpath, d.missing_src_id) for d in out]
    assert ("wiki/entities/X.md", "src-9999") in refs
    # src-0001 is alive — not flagged
    assert all(r[1] != "src-0001" for r in refs)


def test_scan_dead_refs_recurses_subdirs(tmp_path: Path) -> None:
    """raw/ may have subdirs (im_1v1, im_group, minutes, docs, etc). Search all."""
    vault = _vault(tmp_path)
    for sub in ("im_1v1", "im_group", "minutes", "docs"):
        (vault / "raw" / sub).mkdir()
    (vault / "raw" / "minutes" / "src-0007.md").write_text(
        "---\nsrc_id: src-0007\n---\nx\n", encoding="utf-8",
    )
    page = vault / "wiki" / "entities" / "X.md"
    page.write_text(
        "---\npage_type: entity\ntitle: X\nsources: [src-0007]\n"
        "confidence: medium\nneeds_review: false\n---\n\n# X\n",
        encoding="utf-8",
    )
    # All sources alive → no dead refs
    assert lint_cmd.scan_dead_refs(vault) == []


def test_scan_stale_pages_finds_pages_older_than_threshold(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    page = vault / "wiki" / "entities" / "ancient.md"
    page.write_text(
        "---\npage_type: entity\ntitle: ancient\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n"
        "last_modified: 2025-12-01T00:00:00+08:00\n"
        "last_modified_by: ingest\n---\n\n# ancient\n",
        encoding="utf-8",
    )
    out = lint_cmd.scan_stale_pages(vault, today=_dt.date(2026, 5, 1))
    relpaths = [s.page_relpath for s in out]
    assert "wiki/entities/ancient.md" in relpaths


def test_scan_stale_pages_ignores_recent_pages(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    page = vault / "wiki" / "entities" / "fresh.md"
    page.write_text(
        "---\npage_type: entity\ntitle: fresh\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n"
        "last_modified: 2026-04-25T00:00:00+08:00\n"
        "last_modified_by: ingest\n---\n\n# fresh\n",
        encoding="utf-8",
    )
    out = lint_cmd.scan_stale_pages(vault, today=_dt.date(2026, 5, 1))
    assert all("fresh" not in s.page_relpath for s in out)


def test_scan_stale_pages_skips_pages_without_last_modified(tmp_path: Path) -> None:
    """Defensive: malformed pages can't be evaluated for staleness; skip them
    (they show up under missing_sources_pages instead)."""
    vault = _vault(tmp_path)
    page = vault / "wiki" / "entities" / "noTimestamp.md"
    page.write_text(
        "---\npage_type: entity\ntitle: x\nsources: [src-1]\n"
        "confidence: medium\nneeds_review: false\n---\n\n# x\n",
        encoding="utf-8",
    )
    out = lint_cmd.scan_stale_pages(vault, today=_dt.date(2026, 5, 1))
    assert all("noTimestamp" not in s.page_relpath for s in out)


def test_build_report_aggregates_all_scanners(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    rpt = lint_cmd.build_report(vault)
    assert isinstance(rpt, lint_cmd.LintReport)
    # Empty vault → empty report
    assert rpt.is_empty()


def test_emit_prompt_default_contains_static_findings_and_dynamic_rubric(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # Seed one finding from each bucket
    merge_note.write(
        vault_dir=vault, page_type="entity", title="orphaned",
        sources=["src-1"], confidence="medium",
        body="# orphaned\n", author_role="ingest",
    )
    (vault / "index.md").write_text("# 索引\n", encoding="utf-8")
    page = vault / "wiki" / "entities" / "broken.md"
    page.write_text(
        "---\npage_type: entity\ntitle: broken\nsources: []\n"
        "confidence: low\nneeds_review: true\n---\n# broken\n",
        encoding="utf-8",
    )
    prompt = lint_cmd.emit_prompt(vault)
    assert "张三" in prompt
    assert "orphaned" in prompt or "wiki/entities/orphaned.md" in prompt
    assert "broken" in prompt or "wiki/entities/broken.md" in prompt
    # Dynamic-scan rubric reference
    assert "references/prompt-lint.md" in prompt
    # Mentions cross-page contradictions / missing concepts / source gaps
    assert "跨页矛盾" in prompt or "cross-page" in prompt.lower()
    # Finish command
    assert "lint-finish" in prompt


def test_emit_prompt_when_clean_says_clean(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    prompt = lint_cmd.emit_prompt(vault)
    assert "clean" in prompt.lower() or "无健康问题" in prompt


def _git_init_vault(vault: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )


def test_finish_logs_lint_run(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _git_init_vault(vault)
    lint_cmd.finish(vault, findings=4)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "lint" in log
    assert "4 findings" in log


def test_finish_zero_findings_log_says_clean(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _git_init_vault(vault)
    lint_cmd.finish(vault, findings=0)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "lint" in log
    assert "0 findings" in log or "clean" in log.lower()
