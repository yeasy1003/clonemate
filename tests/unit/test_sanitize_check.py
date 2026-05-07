"""Tests for sanitize_check.py."""
from __future__ import annotations

from pathlib import Path

import pytest
from clonemate import sanitize_check  # noqa: E402


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_detects_real_open_id(tmp_path: Path) -> None:
    f = write(tmp_path / "demo.md", "Talked to ou_a1b2c3d4e5f6a7b8 today")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert any(fi.path == f and fi.rule == "open_id" for fi in findings)


def test_allows_placeholder_open_id(tmp_path: Path) -> None:
    f = write(tmp_path / "demo.md", "Like ou_xxxxxxxxxxxxxxxx in the template")
    findings = sanitize_check.scan_path(tmp_path)
    assert not any(fi.path == f for fi in findings)


@pytest.mark.parametrize(
    "rule, real, placeholder",
    [
        ("chat_id", "oc_a1b2c3d4e5f6a7b8", "oc_xxxxxxxxxxxxxxxx"),  # sanitize: allow-line test fixture
        ("app_id", "cli_a1b2c3d4e5f6a7b8", "cli_xxxxxxxxxxxxxxxx"),  # sanitize: allow-line test fixture
        ("union_id", "on_a1b2c3d4e5f6a7b8", "on_xxxxxxxxxxxxxxxx"),  # sanitize: allow-line test fixture
        ("message_id", "om_a1b2c3d4e5f6a7b8", "om_xxxxxxxxxxxxxxxx"),  # sanitize: allow-line test fixture
        ("object_id", "obj_a1b2c3d4e5f6a7b8", "obj_xxxxxxxxxxxxxxxx"),  # sanitize: allow-line test fixture
    ],
)
def test_lark_id_rules(tmp_path: Path, rule: str, real: str, placeholder: str) -> None:
    real_file = write(tmp_path / f"real_{rule}.md", f"id is {real}")
    placeholder_file = write(tmp_path / f"ph_{rule}.md", f"id is {placeholder}")
    findings = sanitize_check.scan_path(tmp_path)
    paths_with_finding = {fi.path for fi in findings if fi.rule == rule}
    assert real_file in paths_with_finding
    assert placeholder_file not in paths_with_finding


@pytest.mark.parametrize(
    "rule, real, placeholder",
    [
        ("docx_token",  "doxcnAbCdEfGhIjKlMn",  "doxcnXXXXXXXXXXXX"),  # sanitize: allow-line test fixture
        ("docx_token",  "doccnAbCdEfGhIjKlMn",  "doccnXXXXXXXXXXXX"),  # sanitize: allow-line test fixture
        ("wiki_token",  "wikcnAbCdEfGhIjKlMn",  "wikcnXXXXXXXXXXXX"),  # sanitize: allow-line test fixture
        ("sheet_token", "shtcnAbCdEfGhIjKlMn",  "shtcnXXXXXXXXXXXX"),  # sanitize: allow-line test fixture
        ("base_token",  "bascnAbCdEfGhIjKlMn",  "bascnXXXXXXXXXXXX"),  # sanitize: allow-line test fixture
        ("minute_token", "mmAbCdEfGhIjKlMn",    "mmXXXXXXXXXXXX"),  # sanitize: allow-line test fixture
        ("filebox_token", "boxcnAbCdEfGhIjKlMn", "boxcnXXXXXXXXXXXX"),  # sanitize: allow-line test fixture
    ],
)
def test_doc_tokens(tmp_path: Path, rule: str, real: str, placeholder: str) -> None:
    real_file = write(tmp_path / f"real_{rule}.md", real)
    ph_file = write(tmp_path / f"ph_{rule}.md", placeholder)
    findings = sanitize_check.scan_path(tmp_path)
    paths = {fi.path for fi in findings if fi.rule == rule}
    assert real_file in paths
    assert ph_file not in paths


@pytest.mark.parametrize(
    "email, should_flag",
    [
        ("zhangsan@acme.com",      True),  # sanitize: allow-line test fixture
        ("zhangsan@gmail.com",     True),  # sanitize: allow-line test fixture
        ("zhangsan@example.com",   False),
        ("alice@example.org",      False),
        ("bob@example.cn",         False),
        ("noreply@example.io",     False),
        ("test@example.test",      False),
    ],
)
def test_email_rule(tmp_path: Path, email: str, should_flag: bool) -> None:
    f = write(tmp_path / "demo.md", f"contact: {email}")
    findings = sanitize_check.scan_path(tmp_path)
    flagged = any(fi.path == f and fi.rule == "email" for fi in findings)
    assert flagged is should_flag


def test_id_card_18_digits_flagged(tmp_path: Path) -> None:
    f = write(tmp_path / "demo.md", "id 110101199003073217")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert any(fi.path == f and fi.rule == "id_card" for fi in findings)


def test_phone_cn_flagged(tmp_path: Path) -> None:
    f = write(tmp_path / "demo.md", "phone 13812345678")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert any(fi.path == f and fi.rule == "phone_cn" for fi in findings)


def test_phone_short_not_flagged(tmp_path: Path) -> None:
    f = write(tmp_path / "demo.md", "version 1234567890")
    findings = sanitize_check.scan_path(tmp_path)
    assert not any(fi.path == f and fi.rule == "phone_cn" for fi in findings)


def test_allow_line_exemption(tmp_path: Path) -> None:
    write(
        tmp_path / "demo.md",
        "ou_a1b2c3d4e5f6a7b8 <!-- sanitize: allow-line example pattern -->",  # sanitize: allow-line test fixture
    )
    findings = sanitize_check.scan_path(tmp_path)
    assert not findings


def test_allow_line_does_not_cross_lines(tmp_path: Path) -> None:
    f = write(
        tmp_path / "demo.md",
        "<!-- sanitize: allow-line ok -->\nou_a1b2c3d4e5f6a7b8\n",  # sanitize: allow-line test fixture
    )
    findings = sanitize_check.scan_path(tmp_path)
    assert any(fi.path == f and fi.rule == "open_id" for fi in findings)


def test_allow_line_python_comment_form(tmp_path: Path) -> None:
    write(
        tmp_path / "demo.py",
        "REAL = 'ou_a1b2c3d4e5f6a7b8'  # sanitize: allow-line doc example",  # sanitize: allow-line test fixture
    )
    findings = sanitize_check.scan_path(tmp_path)
    assert not findings


def test_excludes_dot_git(tmp_path: Path) -> None:
    write(tmp_path / ".git" / "objects" / "ab.cd", "ou_a1b2c3d4e5f6a7b8")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert not findings


def test_excludes_pycache(tmp_path: Path) -> None:
    write(tmp_path / "__pycache__" / "x.cpython-310.pyc", "ou_a1b2c3d4e5f6a7b8")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert not findings


def test_excludes_venv(tmp_path: Path) -> None:
    venv_file = tmp_path / ".venv" / "lib" / "site-packages" / "demo.py"
    write(venv_file, "ou_a1b2c3d4e5f6a7b8")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert not findings


def test_excludes_binary_suffix(tmp_path: Path) -> None:
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"ou_a1b2c3d4e5f6a7b8")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert not findings


def test_includes_fixtures_dir(tmp_path: Path) -> None:
    f = write(tmp_path / "tests" / "fixtures" / "demo.md", "ou_a1b2c3d4e5f6a7b8")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(tmp_path)
    assert any(fi.path == f for fi in findings), "fixtures dir MUST be scanned"


def test_scan_path_single_file(tmp_path: Path) -> None:
    f = write(tmp_path / "single.md", "Talked to ou_a1b2c3d4e5f6a7b8 today")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(f)
    assert len(findings) == 1
    assert findings[0].rule == "open_id"


def test_scan_path_single_file_binary_returns_empty(tmp_path: Path) -> None:
    # \xff\xfe are invalid UTF-8 start bytes, triggering UnicodeDecodeError.
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\xff\xfe ou_a1b2c3d4e5f6a7b8")  # sanitize: allow-line test fixture
    findings = sanitize_check.scan_path(f)
    assert findings == []


def test_main_exits_0_on_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "demo.md", "Hello @example.com 张三")
    rc = sanitize_check.main([str(tmp_path)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_main_exits_1_on_finding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "demo.md", "ou_a1b2c3d4e5f6a7b8")  # sanitize: allow-line test fixture
    rc = sanitize_check.main([str(tmp_path)])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_defaults_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When invoked with no argv, main() should scan Path.cwd()."""
    write(tmp_path / "demo.md", "@example.com is fine")
    monkeypatch.chdir(tmp_path)
    rc = sanitize_check.main([])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_main_argv_none_uses_sys_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When argv=None, main() falls back to sys.argv[1:]."""
    write(tmp_path / "demo.md", "@example.com")
    monkeypatch.setattr("sys.argv", ["clonemate.sanitize_check", str(tmp_path)])
    rc = sanitize_check.main(None)
    assert rc == 0


def test_repo_self_scan_clean(repo_root: Path) -> None:
    """The clonemate repo itself must pass sanitize_check."""
    findings = sanitize_check.scan_path(repo_root)
    assert findings == [], "\n".join(f"{fi.path}:{fi.line} [{fi.rule}] {fi.snippet}" for fi in findings)
