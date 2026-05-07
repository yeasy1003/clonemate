"""E2E plumbing for M7 sync — spec §6.6 invariants."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml
from clonemate import sync_cmd
from clonemate.adapters._base import AdapterResult, FetchContext

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "vaults" / "m7-sync-fixture"


def _copy(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    shutil.copytree(_FIXTURE, vault)
    return vault


def _git_init(vault: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )


class _StubAdapter:
    """Fake adapter whose behavior is parameterized."""
    def __init__(self, *, raise_on_fetch: bool = False, returned_cursor: dict | None = None):
        self.raise_on_fetch = raise_on_fetch
        self.returned_cursor = returned_cursor or {"status": "ok", "last": "2026-05-01"}

    def fetch(self, ctx: FetchContext) -> AdapterResult:
        if self.raise_on_fetch:
            raise RuntimeError("simulated API failure")
        return AdapterResult(raws=[], next_cursor=self.returned_cursor)


def test_sync_cursor_isolation(tmp_path: Path) -> None:
    """spec §6.6 key test: simulate one source failing.
    The successful source's cursor advances; the failed source's cursor
    stays put."""
    vault = _copy(tmp_path)
    _git_init(vault)
    contact_stub = _StubAdapter(returned_cursor={"status": "ok", "last": "2026-05-01"})
    im_stub = _StubAdapter(raise_on_fetch=True)
    fake_adapters = {"contact": contact_stub, "im_1v1": im_stub}

    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources._built_in_adapters", return_value=fake_adapters):
        rep = sync_cmd.sync(vault, my_open_id="ou_xxxxxxxxxxxxxxxx")

    assert rep.per_source["contact"].failed is False
    assert rep.per_source["im_1v1"].failed is True
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    # contact cursor advanced
    assert cy["cursors"]["contact"]["status"] == "ok"
    # im_1v1 cursor untouched (stays empty / no entry)
    assert "im_1v1" not in cy.get("cursors", {}) or not cy["cursors"].get("im_1v1")


def test_sync_skipped_source_recovery(tmp_path: Path) -> None:
    """spec §6.6 key test: failed source stays at original cursor; the
    next sync fetches the SAME window the user would have seen if the
    first sync had succeeded."""
    vault = _copy(tmp_path)
    _git_init(vault)

    # First sync — both sources fail
    fail_stub = _StubAdapter(raise_on_fetch=True)
    adapters_first = {"contact": fail_stub, "im_1v1": fail_stub}
    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources._built_in_adapters", return_value=adapters_first):
        sync_cmd.sync(vault, my_open_id="ou_xxxxxxxxxxxxxxxx")

    cy_after_first = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    # Both cursors empty (nothing advanced)
    assert not cy_after_first.get("cursors", {}).get("contact")
    assert not cy_after_first.get("cursors", {}).get("im_1v1")

    # Second sync — now succeeds
    ok_stub = _StubAdapter(returned_cursor={"status": "ok", "last": "2026-05-01"})
    adapters_second = {"contact": ok_stub, "im_1v1": ok_stub}
    captured_ctx: list[FetchContext] = []
    real_fetch = ok_stub.fetch

    def capturing_fetch(ctx: FetchContext) -> AdapterResult:
        captured_ctx.append(ctx)
        return real_fetch(ctx)

    ok_stub.fetch = capturing_fetch  # type: ignore[assignment]

    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources._built_in_adapters", return_value=adapters_second):
        sync_cmd.sync(vault, my_open_id="ou_xxxxxxxxxxxxxxxx")

    # The retry passed a context with the SAME cursor (empty) the first
    # call had. No window was skipped.
    assert any(not ctx.cursor for ctx in captured_ctx)


def test_sync_idempotent(tmp_path: Path) -> None:
    """spec §6.6 key test: two syncs with no new data == same end state.
    raw not duplicated; cursor advances exactly once."""
    vault = _copy(tmp_path)
    _git_init(vault)

    # First sync — adapter returns one raw candidate. RawCandidate is
    # imported from `clonemate.raw_writer` (NOT adapters._base) and has
    # fields: source_type, relative_path, hash_input, frontmatter, content.
    from clonemate.raw_writer import RawCandidate
    raw_one = RawCandidate(
        source_type="contact",
        relative_path="contact/profile.md",
        hash_input="张三 contact profile",
        frontmatter={"src_type": "contact",
                     "author_open_id": "ou_xxxxxxxxxxxxxxxx",
                     "collected_at": "2026-05-01T10:00:00+08:00"},
        content="# Profile\n张三\n",
    )

    class OnceStub:
        """Returns raw_one on first call, empty on second."""
        def __init__(self) -> None:
            self.calls = 0
        def fetch(self, ctx: FetchContext) -> AdapterResult:
            self.calls += 1
            if self.calls == 1:
                return AdapterResult(
                    raws=[raw_one], next_cursor={"status": "ok", "last": "2026-05-01"},
                )
            return AdapterResult(raws=[], next_cursor={"status": "ok", "last": "2026-05-01"})

    stub = OnceStub()
    adapters = {"contact": stub, "im_1v1": _StubAdapter()}
    with patch("clonemate.profile_check.verify_profile"), \
         patch("clonemate.fetch_sources._built_in_adapters", return_value=adapters):
        sync_cmd.sync(vault, my_open_id="ou_xxxxxxxxxxxxxxxx")
        sync_cmd.sync(vault, my_open_id="ou_xxxxxxxxxxxxxxxx")

    # Raw was written exactly once; second call returned 0 new
    raw_files = list((vault / "raw" / "contact").glob("*.md"))
    assert len(raw_files) == 1
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    assert cy["cursors"]["contact"]["status"] == "ok"
    assert stub.calls == 2  # both syncs invoked the adapter
