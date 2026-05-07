# tests/unit/test_main_entry.py
from __future__ import annotations

from pathlib import Path

from clonemate import __main__ as main_entry


def test_clone_subcommand_routes_to_clone_cmd(monkeypatch, tmp_path: Path) -> None:
    called: dict = {}

    def fake_clone(*, root, handle, my_open_id, profile, since, slug=None, picker=None):
        called.update(root=root, handle=handle, my_open_id=my_open_id, profile=profile, since=since)
        from clonemate.fetch_sources import FetchReport
        return FetchReport()

    monkeypatch.setattr(main_entry, "clone", fake_clone)
    rc = main_entry.main([
        "clone", "张三",
        "--root", str(tmp_path),
        "--my-open-id", "ou_xxxxxxxxxxxxxxxx",  # sanitize: allow-line test fixture
        "--profile", "claude-code",
        "--since", "180d",
    ])
    assert rc == 0
    assert called["handle"] == "张三"
    assert called["since"] == "180d"
