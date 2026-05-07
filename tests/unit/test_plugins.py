from __future__ import annotations

from clonemate import plugins


def test_discover_returns_only_allowed(monkeypatch) -> None:
    """Only plugins listed in plugins_allowed are returned."""

    class FakeEP:
        def __init__(self, name, value):
            self.name = name
            self.value = value

        def load(self):
            return f"loaded-{self.name}"

    fake_eps = [FakeEP("meego", "x"), FakeEP("custom", "y")]
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: fake_eps)

    out = plugins.discover(allowlist=["meego"])
    assert list(out.keys()) == ["meego"]
    assert out["meego"] == "loaded-meego"


def test_discover_empty_allowlist_returns_nothing(monkeypatch) -> None:
    class FakeEP:
        def __init__(self, name):
            self.name = name

        def load(self):
            return self.name

    monkeypatch.setattr(plugins, "_iter_entry_points", lambda: [FakeEP("meego")])
    assert plugins.discover(allowlist=[]) == {}
