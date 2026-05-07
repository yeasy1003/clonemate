from __future__ import annotations

import pytest
from clonemate import lark_cli, resolve


def _auth_status_response() -> dict:
    return {"appId": "cli_xxxxxxxxxxxxxxxx", "userOpenId": "ou_yyyyyyyyyyyyyyyy"}  # sanitize: allow-line test fixture


def test_open_id_passthrough(monkeypatch) -> None:
    """If handle is already an open_id, no contact search is needed; we still
    record app_id from `lark-cli auth status`."""

    def fake_run(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _auth_status_response()
        pytest.fail(f"unexpected args: {args}")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    oid = "ou_a1b2c3d4e5f6a7b8"  # sanitize: allow-line test fixture
    candidates = resolve.resolve_handle(oid, profile="claude-code")
    assert len(candidates) == 1
    assert candidates[0].open_id == oid
    assert candidates[0].app_id == "cli_xxxxxxxxxxxxxxxx"


def test_email_search(monkeypatch) -> None:
    def fake_run(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _auth_status_response()
        if args[:2] == ["contact", "+search-user"]:
            return {"data": {"users": [{
                "open_id": "ou_xxxxxxxxxxxxxxxx",
                "localized_name": "张三",
                "email": "zhangsan@example.com",
            }]}}
        pytest.fail(f"unexpected args: {args}")

    monkeypatch.setattr(lark_cli, "run", fake_run)
    candidates = resolve.resolve_handle("zhangsan@example.com", profile="claude-code")
    assert len(candidates) == 1
    assert candidates[0].open_id == "ou_xxxxxxxxxxxxxxxx"
    assert candidates[0].display_name == "张三"
    assert candidates[0].email == "zhangsan@example.com"


def test_email_no_match_raises(monkeypatch) -> None:
    def fake_run(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _auth_status_response()
        return {"data": {"users": []}}

    monkeypatch.setattr(lark_cli, "run", fake_run)
    with pytest.raises(resolve.ResolveError) as exc:
        resolve.resolve_handle("ghost@example.com", profile="claude-code")
    assert "no match" in str(exc.value).lower()


def test_name_returns_multiple_candidates(monkeypatch) -> None:
    def fake_run(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _auth_status_response()
        if args[:2] == ["contact", "+search-user"]:
            return {"data": {"users": [
                {"open_id": "ou_xxxxxxxxxxxxxxxx", "localized_name": "张三", "email": "zhangsan-eng@example.com"},
                {"open_id": "ou_xxxxxxxxxxxxxxxy", "localized_name": "张三", "email": "zhangsan-pm@example.com"},  # sanitize: allow-line test fixture
            ]}}
        return {}

    monkeypatch.setattr(lark_cli, "run", fake_run)
    candidates = resolve.resolve_handle("张三", profile="claude-code")
    assert len(candidates) == 2
    assert {c.email for c in candidates} == {"zhangsan-eng@example.com", "zhangsan-pm@example.com"}
