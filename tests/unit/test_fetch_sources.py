# tests/unit/test_fetch_sources.py
from __future__ import annotations

from pathlib import Path

import yaml
from clonemate import fetch_sources
from clonemate.adapters._base import AdapterResult
from clonemate.raw_writer import RawCandidate


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan",
        "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx", "app_id": "cli_xxxxxxxxxxxxxxxx"},
        "display_name": "张三",
        "profile": "claude-code",
        "cursors": {"contact": {"status": "pending"}},
        "sources_enabled": {"contact": True},
        "window": {"default_since": "180d"},
        "quota": {"per_source_max_messages": 1000, "per_source_max_mb": 100},
        "filters": {},
        "plugins_allowed": [],
    }, allow_unicode=True), encoding="utf-8")
    return vault


def test_single_source_happy_path(tmp_path: Path, monkeypatch) -> None:
    vault = _make_vault(tmp_path)

    class FakeAdapter:
        name = "contact"
        def fetch(self, ctx):
            return AdapterResult(
                raws=[RawCandidate("contact", "contact/profile.md", "fake", {"author_open_id": ctx.open_id}, "# 张三")],
                next_cursor={"status": "ok", "last_fetched_at": "2026-04-29T10:00:00+08:00"},
            )

    monkeypatch.setattr(fetch_sources, "_built_in_adapters", lambda: {"contact": FakeAdapter()})

    report = fetch_sources.run(vault_dir=vault, my_open_id="ou_xxxxxxxxxxxxxxxx", since_str="180d")
    assert report.per_source["contact"].written == 1
    assert report.per_source["contact"].skipped == 0
    assert report.per_source["contact"].failed is False
    # cursor advanced
    new_yaml = yaml.safe_load((vault / "_clone.yaml").read_text())
    assert new_yaml["cursors"]["contact"]["status"] == "ok"
    # raw file present (path is hash-suffixed: profile-<8 hex>.md)
    raw_files = list((vault / "raw" / "contact").glob("profile-*.md"))
    assert len(raw_files) == 1


def test_failed_source_does_not_advance_cursor(tmp_path: Path, monkeypatch) -> None:
    vault = _make_vault(tmp_path)

    class FailingAdapter:
        name = "contact"
        def fetch(self, ctx):
            raise RuntimeError("API rate limit")

    monkeypatch.setattr(fetch_sources, "_built_in_adapters", lambda: {"contact": FailingAdapter()})

    report = fetch_sources.run(vault_dir=vault, my_open_id="ou_xxxxxxxxxxxxxxxx", since_str="180d")
    assert report.per_source["contact"].failed is True
    assert "rate limit" in report.per_source["contact"].error
    new_yaml = yaml.safe_load((vault / "_clone.yaml").read_text())
    # cursor is still pending
    assert new_yaml["cursors"]["contact"]["status"] == "pending"
    # error log written
    assert (vault / "raw" / "contact" / ".error.log").is_file()
    log_text = (vault / "raw" / "contact" / ".error.log").read_text()
    assert "rate limit" in log_text


def test_quota_skipped_source(tmp_path: Path, monkeypatch) -> None:
    vault = _make_vault(tmp_path)

    class QuotaAdapter:
        name = "contact"
        def fetch(self, ctx):
            return AdapterResult(raws=[], next_cursor=ctx.cursor, skipped_reason="quota exceeded (1500 > 1000)")

    monkeypatch.setattr(fetch_sources, "_built_in_adapters", lambda: {"contact": QuotaAdapter()})
    report = fetch_sources.run(vault_dir=vault, my_open_id="ou_xxxxxxxxxxxxxxxx", since_str="180d")
    sr = report.per_source["contact"]
    assert sr.skipped_reason and "quota" in sr.skipped_reason
    assert sr.failed is False


def _make_multi_source_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan",
        "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx", "app_id": "cli_xxxxxxxxxxxxxxxx"},
        "display_name": "张三",
        "profile": "claude-code",
        "cursors": {"contact": {"status": "pending"}, "minutes": {"status": "pending"}},
        "sources_enabled": {"contact": True, "minutes": True},
        "window": {"default_since": "180d"},
        "quota": {"per_source_max_messages": 1000},
        "filters": {},
        "plugins_allowed": [],
    }, allow_unicode=True), encoding="utf-8")
    return vault


def test_multi_source_partial_failure(tmp_path: Path, monkeypatch) -> None:
    vault = _make_multi_source_vault(tmp_path)

    class GoodAdapter:
        name = "contact"
        def fetch(self, ctx):
            return AdapterResult(
                raws=[RawCandidate("contact", "contact/profile.md", "ok", {"author_open_id": ctx.open_id}, "# 张三")],
                next_cursor={"status": "ok"},
            )

    class BadAdapter:
        name = "minutes"
        def fetch(self, ctx):
            raise RuntimeError("minutes service unreachable")

    monkeypatch.setattr(
        fetch_sources, "_built_in_adapters",
        lambda: {"contact": GoodAdapter(), "minutes": BadAdapter()},
    )
    report = fetch_sources.run(vault_dir=vault, my_open_id="ou_xxxxxxxxxxxxxxxx", since_str="180d")
    assert report.per_source["contact"].written == 1
    assert report.per_source["contact"].failed is False
    assert report.per_source["minutes"].failed is True

    new_yaml = yaml.safe_load((vault / "_clone.yaml").read_text())
    assert new_yaml["cursors"]["contact"]["status"] == "ok"      # advanced
    assert new_yaml["cursors"]["minutes"]["status"] == "pending"  # NOT advanced


def test_partial_status_holds_last_modified_and_surfaces_errors(tmp_path: Path, monkeypatch) -> None:
    """Codex Finding 4 (round 2): adapter status='partial' MUST be surfaced as
    SourceReport.partial_errors and per-doc errors logged. cursor's last_modified_at
    is preserved so the next sync re-fetches failed docs."""
    vault = _make_vault(tmp_path)

    class PartialDocs:
        name = "contact"  # piggy-back on the contact slot since vault enables it
        def fetch(self, ctx):
            return AdapterResult(
                raws=[RawCandidate("contact", "contact/profile.md", "ok", {"author_open_id": ctx.open_id}, "# 张三")],
                next_cursor={
                    "status": "partial",
                    "last_modified_at": "2025-12-01T00:00:00+00:00",
                    "per_doc_errors": {"doxcnAAAAAAAAAAAA": "doc inaccessible"},  # sanitize: allow-line plan fixture
                },
            )

    monkeypatch.setattr(fetch_sources, "_built_in_adapters", lambda: {"contact": PartialDocs()})
    report = fetch_sources.run(vault_dir=vault, my_open_id="ou_xxxxxxxxxxxxxxxx", since_str="180d")

    sr = report.per_source["contact"]
    assert sr.failed is False
    assert sr.partial_errors == {"doxcnAAAAAAAAAAAA": "doc inaccessible"}  # sanitize: allow-line plan fixture
    # Successful raw still emitted
    assert sr.written == 1

    # Cursor saved with status='partial'; last_modified_at NOT advanced past the prior boundary.
    new_yaml = yaml.safe_load((vault / "_clone.yaml").read_text())
    assert new_yaml["cursors"]["contact"]["status"] == "partial"
    assert new_yaml["cursors"]["contact"]["last_modified_at"] == "2025-12-01T00:00:00+00:00"

    # error.log written with per-doc detail
    log_text = (vault / "raw" / "contact" / ".error.log").read_text(encoding="utf-8")
    assert "doxcnAAAAAAAAAAAA" in log_text  # sanitize: allow-line plan fixture
    assert "doc inaccessible" in log_text


def test_doc_comments_receives_docs_owned_tokens(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "zhangsan"
    (vault / "raw").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan",
        "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx", "app_id": "cli_xxxxxxxxxxxxxxxx"},
        "display_name": "张三", "profile": "claude-code",
        "cursors": {
            "docs_owned": {"status": "pending"},
            "doc_comments": {"doc_to_comment_id": {}, "status": "pending"},
        },
        "sources_enabled": {"docs_owned": True, "doc_comments": True},
        "window": {"default_since": "180d"}, "quota": {"per_source_max_messages": 1000},
        "filters": {}, "plugins_allowed": [],
    }, allow_unicode=True), encoding="utf-8")

    class FakeDocsOwned:
        name = "docs_owned"
        def fetch(self, ctx):
            return AdapterResult(raws=[
                RawCandidate(
                    "docs", "docs/doxcnXXXXXXXXXXXX.md", "doc1",
                    {"doc_token": "doxcnXXXXXXXXXXXX", "author_open_id": ctx.open_id}, "# doc",
                ),
                RawCandidate(
                    "docs", "docs/wikcnXXXXXXXXXXXX.md", "doc2",
                    {"doc_token": "wikcnXXXXXXXXXXXX", "author_open_id": ctx.open_id}, "# wiki",
                ),
            ], next_cursor={"status": "ok"})

    captured_ctx: dict = {}

    class FakeDocComments:
        name = "doc_comments"
        def fetch(self, ctx):
            entries = ctx.cursor.get("doc_entries_to_scan", []) or []
            captured_ctx["tokens"] = [e["token"] for e in entries]
            return AdapterResult(raws=[], next_cursor={"doc_to_comment_id": {}, "status": "ok"})

    monkeypatch.setattr(
        fetch_sources, "_built_in_adapters",
        lambda: {"docs_owned": FakeDocsOwned(), "doc_comments": FakeDocComments()},
    )
    fetch_sources.run(vault_dir=vault, my_open_id="ou_xxxxxxxxxxxxxxxx", since_str="180d")
    assert sorted(captured_ctx["tokens"]) == ["doxcnXXXXXXXXXXXX", "wikcnXXXXXXXXXXXX"]
