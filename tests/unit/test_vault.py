"""Tests for vault.py."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from clonemate import git_ops, vault


# Bypass git_ops.check_filter_repo / init_vault_repo / install_pre_push_hook
# in unit tests; we test those primitives separately.
@pytest.fixture(autouse=True)
def stub_git(monkeypatch):
    monkeypatch.setattr(git_ops, "check_filter_repo", lambda: None)
    monkeypatch.setattr(git_ops, "init_vault_repo", lambda d: (Path(d) / ".git").mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(git_ops, "install_pre_push_hook", lambda d: None)


def test_init_creates_directory_tree(tmp_path: Path) -> None:
    vault_dir = tmp_path / "zhangsan"
    vault.init(
        vault_dir=vault_dir,
        slug="zhangsan",
        open_id="ou_xxxxxxxxxxxxxxxx",
        app_id="cli_xxxxxxxxxxxxxxxx",
        display_name="张三",
        profile="claude-code",
    )
    assert (vault_dir / "raw").is_dir()
    assert (vault_dir / "wiki" / "entities").is_dir()
    assert (vault_dir / "wiki" / "concepts").is_dir()
    assert (vault_dir / "wiki" / "syntheses").is_dir()
    assert (vault_dir / "wiki" / "sources").is_dir()
    assert (vault_dir / "_clone.yaml").is_file()
    assert (vault_dir / "index.md").is_file()
    assert (vault_dir / "log.md").is_file()
    assert (vault_dir / "SKILL.md").is_file()
    assert (vault_dir / ".clonemate-version").is_file()


def test_init_writes_correct_clone_yaml(tmp_path: Path) -> None:
    vault_dir = tmp_path / "zhangsan"
    vault.init(
        vault_dir=vault_dir,
        slug="zhangsan",
        open_id="ou_xxxxxxxxxxxxxxxx",
        app_id="cli_xxxxxxxxxxxxxxxx",
        display_name="张三",
        profile="claude-code",
        aliases=["张三", "Zhang San", "zhangsan@example.com"],
    )
    data = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    assert data["slug"] == "zhangsan"
    assert data["identity"]["open_id"] == "ou_xxxxxxxxxxxxxxxx"
    assert data["identity"]["app_id"] == "cli_xxxxxxxxxxxxxxxx"
    assert data["display_name"] == "张三"
    assert "Zhang San" in data["aliases"]
    assert data["profile"] == "claude-code"
    assert data["sources_enabled"]["contact"] is True
    assert data["sources_enabled"]["meego"] is False
    assert data["window"]["default_since"] == "180d"
    assert "cursors" in data
    assert data["cursors"]["im_1v1"]["status"] == "pending"
    assert data["cursors"]["im_1v1"]["chat_to_msg"] == {}


def test_init_writes_vault_gitignore_excluding_raw(tmp_path: Path) -> None:
    vault_dir = tmp_path / "zhangsan"
    vault.init(
        vault_dir=vault_dir,
        slug="zhangsan",
        open_id="ou_xxxxxxxxxxxxxxxx",
        app_id="cli_xxxxxxxxxxxxxxxx",
        display_name="张三",
        profile="claude-code",
    )
    gi = (vault_dir / ".gitignore").read_text(encoding="utf-8")
    assert "raw/" in gi
    assert "*.error.log" in gi


def test_init_calls_check_filter_repo_first(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(git_ops, "check_filter_repo", lambda: calls.append("check_filter_repo"))
    def _fake_init_vault_repo(d: object) -> None:
        calls.append("init_vault_repo")
        (Path(d) / ".git").mkdir(parents=True, exist_ok=True)  # type: ignore[arg-type]

    monkeypatch.setattr(git_ops, "init_vault_repo", _fake_init_vault_repo)
    monkeypatch.setattr(git_ops, "install_pre_push_hook", lambda d: calls.append("install_pre_push_hook"))

    vault_dir = tmp_path / "zhangsan"
    vault.init(
        vault_dir=vault_dir, slug="zhangsan",
        open_id="ou_xxxxxxxxxxxxxxxx", app_id="cli_xxxxxxxxxxxxxxxx",
        display_name="张三", profile="claude-code",
    )
    assert calls[0] == "check_filter_repo"
    assert "init_vault_repo" in calls
    assert "install_pre_push_hook" in calls
    assert calls.index("install_pre_push_hook") > calls.index("init_vault_repo")


def test_init_aborts_when_filter_repo_missing(tmp_path: Path, monkeypatch) -> None:
    def boom() -> None:
        raise git_ops.MissingDependencyError("git-filter-repo missing")

    monkeypatch.setattr(git_ops, "check_filter_repo", boom)
    monkeypatch.setattr(git_ops, "init_vault_repo", lambda d: pytest.fail("should not be called"))
    monkeypatch.setattr(git_ops, "install_pre_push_hook", lambda d: pytest.fail("should not be called"))

    with pytest.raises(git_ops.MissingDependencyError):
        vault.init(
            vault_dir=tmp_path / "x", slug="x",
            open_id="ou_xxxxxxxxxxxxxxxx", app_id="cli_xxxxxxxxxxxxxxxx",
            display_name="X", profile="claude-code",
        )


def test_list_empty_root(tmp_path: Path) -> None:
    assert vault.list_vaults(tmp_path) == []


def test_list_finds_vaults(tmp_path: Path) -> None:
    vault.init(
        vault_dir=tmp_path / "zhangsan", slug="zhangsan",
        open_id="ou_xxxxxxxxxxxxxxxx", app_id="cli_xxxxxxxxxxxxxxxx",
        display_name="张三", profile="claude-code",
    )
    vault.init(
        vault_dir=tmp_path / "lisi", slug="lisi",
        open_id="ou_xxxxxxxxxxxxxxxx", app_id="cli_xxxxxxxxxxxxxxxx",
        display_name="李四", profile="claude-code",
    )
    vaults = vault.list_vaults(tmp_path)
    slugs = {v["slug"] for v in vaults}
    assert slugs == {"zhangsan", "lisi"}


def test_list_skips_non_vault_dirs(tmp_path: Path) -> None:
    (tmp_path / "not-a-vault").mkdir()
    (tmp_path / "another").mkdir()
    (tmp_path / "another" / "random.txt").write_text("hello")
    assert vault.list_vaults(tmp_path) == []


def test_rename_moves_dir_and_updates_yaml(tmp_path: Path) -> None:
    vault.init(
        vault_dir=tmp_path / "zhangsan", slug="zhangsan",
        open_id="ou_xxxxxxxxxxxxxxxx", app_id="cli_xxxxxxxxxxxxxxxx",
        display_name="张三", profile="claude-code",
    )
    new_dir = vault.rename(root=tmp_path, old_slug="zhangsan", new_slug="zhangsan-2")
    assert new_dir == tmp_path / "zhangsan-2"
    assert not (tmp_path / "zhangsan").exists()
    assert (tmp_path / "zhangsan-2" / "_clone.yaml").is_file()
    data = yaml.safe_load((tmp_path / "zhangsan-2" / "_clone.yaml").read_text(encoding="utf-8"))
    assert data["slug"] == "zhangsan-2"


def test_rename_collision_raises(tmp_path: Path) -> None:
    vault.init(vault_dir=tmp_path / "a", slug="a", open_id="ou_xxxxxxxxxxxxxxxx",
               app_id="cli_xxxxxxxxxxxxxxxx", display_name="A", profile="claude-code")
    vault.init(vault_dir=tmp_path / "b", slug="b", open_id="ou_xxxxxxxxxxxxxxxx",
               app_id="cli_xxxxxxxxxxxxxxxx", display_name="B", profile="claude-code")
    with pytest.raises(FileExistsError):
        vault.rename(root=tmp_path, old_slug="a", new_slug="b")


def test_rename_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        vault.rename(root=tmp_path, old_slug="ghost", new_slug="x")


def test_cli_init(tmp_path: Path) -> None:
    rc = vault.main([
        "init",
        "--root", str(tmp_path),
        "--slug", "zhangsan",
        "--open-id", "ou_xxxxxxxxxxxxxxxx",
        "--app-id", "cli_xxxxxxxxxxxxxxxx",
        "--display-name", "张三",
        "--profile", "claude-code",
    ])
    assert rc == 0
    assert (tmp_path / "zhangsan" / "_clone.yaml").is_file()


def test_cli_list_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = vault.main(["list", "--root", str(tmp_path)])
    assert rc == 0
    assert "no vaults" in capsys.readouterr().out.lower()


def test_cli_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        vault.main(["bogus"])


# ---------------------------------------------------------------------------
# M6 Task 0b — iter_vaults_under_root (list vault dirs under a root)
# ---------------------------------------------------------------------------


def test_iter_vaults_under_root_returns_dirs_with_clone_yaml(tmp_path: Path) -> None:
    """Each direct subdir of root that has _clone.yaml is a vault."""
    from clonemate import vault as vault_mod
    root = tmp_path / "files" / "clonemate"
    for slug in ("zhangsan", "lisi", "wangwu"):
        v = root / slug
        v.mkdir(parents=True)
        (v / "_clone.yaml").write_text(
            yaml.safe_dump({"slug": slug, "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx"}},
                           allow_unicode=True), encoding="utf-8",
        )
    # A non-vault sibling (no _clone.yaml) is skipped
    (root / "scratch").mkdir()
    (root / "scratch" / "notes.md").write_text("nope", encoding="utf-8")

    vaults = vault_mod.iter_vaults_under_root(root)
    assert [v.name for v in vaults] == ["lisi", "wangwu", "zhangsan"]


def test_iter_vaults_under_root_handles_missing_root(tmp_path: Path) -> None:
    from clonemate import vault as vault_mod
    out = vault_mod.iter_vaults_under_root(tmp_path / "does-not-exist")
    assert out == []


def test_iter_vaults_under_root_does_not_recurse(tmp_path: Path) -> None:
    """Only direct children — not nested vaults-inside-vaults."""
    from clonemate import vault as vault_mod
    root = tmp_path / "root"
    inner = root / "outer" / "inner"
    inner.mkdir(parents=True)
    (root / "outer" / "_clone.yaml").write_text(
        yaml.safe_dump({"slug": "outer"}, allow_unicode=True), encoding="utf-8",
    )
    (inner / "_clone.yaml").write_text(
        yaml.safe_dump({"slug": "inner"}, allow_unicode=True), encoding="utf-8",
    )
    vaults = vault_mod.iter_vaults_under_root(root)
    assert [v.name for v in vaults] == ["outer"]
