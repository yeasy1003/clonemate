# tests/integration/test_clone_cmd.py
from __future__ import annotations

from pathlib import Path

import pytest
from clonemate import clone_cmd, fetch_sources, git_ops, resolve
from clonemate.adapters._base import AdapterResult
from clonemate.raw_writer import RawCandidate


def test_slugify_chinese_returns_empty() -> None:
    """`_slugify('张三')` MUST return '' (no ASCII letters); caller falls back to email/--slug.

    NFKD on Chinese keeps Chinese codepoints, so .encode('ascii', 'ignore') yields b''.
    The previous implementation `or name.lower()` returned the original Chinese — that's
    a bug because vault paths must be ASCII-friendly per spec §3 decision 4 slug semantics.
    Codex Finding 3 (round 2).
    """
    assert clone_cmd._slugify("张三") == ""
    assert clone_cmd._slugify("Zhang San") == "zhang-san"
    assert clone_cmd._slugify("Alice") == "alice"


def test_clone_uses_email_local_part_when_display_name_is_chinese(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(git_ops, "check_filter_repo", lambda: None)
    monkeypatch.setattr(
        git_ops,
        "init_vault_repo",
        lambda d: (Path(d) / ".git").mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(git_ops, "install_pre_push_hook", lambda d: None)

    monkeypatch.setattr(
        resolve,
        "resolve_handle",
        lambda h, *, profile: [
            resolve.Candidate(  # sanitize: allow-line test fixture
                open_id="ou_xxxxxxxxxxxxxxxx",
                app_id="cli_xxxxxxxxxxxxxxxx",
                display_name="张三",
                email="zhangsan@example.com",
            ),
        ],
    )

    class FakeContact:
        name = "contact"

        def fetch(self, ctx):
            return AdapterResult(
                raws=[
                    RawCandidate(
                        "contact",
                        "contact/profile.md",
                        "ok",
                        {"author_open_id": ctx.open_id},
                        "# 张三",
                    ),
                ],
                next_cursor={"status": "ok"},
            )

    monkeypatch.setattr(fetch_sources, "_built_in_adapters", lambda: {"contact": FakeContact()})

    report = clone_cmd.clone(
        root=tmp_path,
        handle="张三",
        my_open_id="ou_xxxxxxxxxxxxxxxx",  # sanitize: allow-line test fixture
        profile="claude-code",
        since="180d",
    )

    # email local-part fallback → slug='zhangsan'
    vault = tmp_path / "zhangsan"
    assert (vault / "_clone.yaml").is_file()
    raw_files = list((vault / "raw" / "contact").glob("profile-*.md"))
    assert len(raw_files) == 1
    assert report.per_source["contact"].written == 1


def test_clone_uses_explicit_slug_override(tmp_path: Path, monkeypatch) -> None:
    """Explicit --slug always wins, even when display_name has ASCII."""
    monkeypatch.setattr(git_ops, "check_filter_repo", lambda: None)
    monkeypatch.setattr(
        git_ops,
        "init_vault_repo",
        lambda d: (Path(d) / ".git").mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(git_ops, "install_pre_push_hook", lambda d: None)

    monkeypatch.setattr(
        resolve,
        "resolve_handle",
        lambda h, *, profile: [
            resolve.Candidate(  # sanitize: allow-line test fixture
                open_id="ou_xxxxxxxxxxxxxxxx",
                app_id="cli_xxxxxxxxxxxxxxxx",
                display_name="Alice",
                email="alice@example.com",
            ),
        ],
    )
    monkeypatch.setattr(fetch_sources, "_built_in_adapters", lambda: {})

    clone_cmd.clone(
        root=tmp_path,
        handle="alice@example.com",
        slug="my-friend",
        my_open_id="ou_xxxxxxxxxxxxxxxx",  # sanitize: allow-line test fixture
        profile="claude-code",
        since="180d",
    )
    assert (tmp_path / "my-friend" / "_clone.yaml").is_file()


def test_clone_raises_when_no_ascii_slug_derivable(tmp_path: Path, monkeypatch) -> None:
    """No display_name ASCII + no email + no --slug → SlugRequiredError."""
    monkeypatch.setattr(
        resolve,
        "resolve_handle",
        lambda h, *, profile: [
            resolve.Candidate(  # sanitize: allow-line test fixture
                open_id="ou_xxxxxxxxxxxxxxxx",
                app_id="cli_xxxxxxxxxxxxxxxx",
                display_name="张三",
                email=None,
            ),
        ],
    )
    with pytest.raises(clone_cmd.SlugRequiredError):
        clone_cmd.clone(
            root=tmp_path,
            handle="张三",
            my_open_id="ou_xxxxxxxxxxxxxxxx",  # sanitize: allow-line test fixture
            profile="claude-code",
            since="180d",
        )


def test_clone_aborts_when_vault_exists(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "zhangsan").mkdir()
    monkeypatch.setattr(
        resolve,
        "resolve_handle",
        lambda h, *, profile: [
            resolve.Candidate(  # sanitize: allow-line test fixture
                open_id="ou_xxxxxxxxxxxxxxxx",
                app_id="cli_xxxxxxxxxxxxxxxx",
                display_name="张三",
                email="zhangsan@example.com",
            ),
        ],
    )
    with pytest.raises(clone_cmd.VaultExistsError):
        clone_cmd.clone(
            root=tmp_path,
            handle="张三",
            my_open_id="ou_xxxxxxxxxxxxxxxx",  # sanitize: allow-line test fixture
            profile="claude-code",
            since="180d",
        )
