"""Tests for feed parsers."""
from __future__ import annotations

from pathlib import Path

import pytest
from clonemate import feed_parsers
from clonemate.feed_parsers._base import FeedParser, ParserUnavailable  # noqa: F401


def test_registry_has_text_parser() -> None:
    parsers = feed_parsers.list_parsers()
    names = [p.name for p in parsers]
    assert "text" in names


def test_dispatch_md_file_picks_text_parser(tmp_path: Path) -> None:
    f = tmp_path / "note.md"
    f.write_text("# hello\n", encoding="utf-8")
    p = feed_parsers.dispatch(str(f))
    assert p is not None
    assert p.name == "text"


def test_dispatch_unknown_input_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "weird.xyz"
    f.write_text("?", encoding="utf-8")
    assert feed_parsers.dispatch(str(f)) is None


def test_detect_input_dash_raises_when_stdin_is_tty(monkeypatch) -> None:
    """Codex round 3 Finding G: `_detect_input("-")` must raise StdinIsTtyError
    instead of blocking, when stdin is a TTY (no piped content)."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(feed_parsers.StdinIsTtyError):
        feed_parsers._detect_input("-")


def test_detect_input_dash_works_when_stdin_piped(monkeypatch) -> None:
    """Sanity: with non-TTY stdin (pipe/redirect), `-` is accepted."""
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("piped content\n"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    fi = feed_parsers._detect_input("-")
    assert fi.is_stdin
    assert fi.body_bytes == b"piped content\n"


# -----------------------------------------------------------------------------
# Task 7 — text + fact parsers
# -----------------------------------------------------------------------------


def test_text_parser_handles_md_file(tmp_path: Path) -> None:
    from clonemate.feed_parsers.text import TextParser

    f = tmp_path / "note.md"
    f.write_text("# hi\nbody\n", encoding="utf-8")
    p = TextParser()
    fi = feed_parsers._detect_input(str(f))
    assert p.can_handle(fi)
    raws = p.parse(fi)
    assert len(raws) == 1
    assert "body" in raws[0].content


def test_text_parser_handles_stdin_content(tmp_path: Path) -> None:
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.text import TextParser

    fi = FeedInput(raw_arg="-", is_stdin=True, body_bytes=b"raw content\n")
    p = TextParser()
    assert p.can_handle(fi)
    raws = p.parse(fi)
    assert raws[0].content == "raw content\n"


def test_text_parser_does_not_handle_url() -> None:
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.text import TextParser

    fi = FeedInput(raw_arg="https://example.com", is_url=True)
    assert TextParser().can_handle(fi) is False


def test_fact_parser_writes_wiki_via_merge_note(tmp_path: Path) -> None:
    """`--fact "..." --confidence X` writes a synthesis page directly,
    bypassing the LLM ingest pipeline."""
    import yaml as _yaml
    from clonemate.feed_parsers.fact import FactParser

    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(
        _yaml.safe_dump(
            {
                "slug": "x",
                "identity": {
                    "open_id": "ou_xxxxxxxxxxxxxxxx",
                    "app_id": "cli_xxxxxxxxxxxxxxxx",
                },
                "display_name": "X",
                "profile": "claude-code",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    p = FactParser()
    p.write_directly(
        vault_dir=vault,
        fact_text="ta 喜欢喝咖啡",
        confidence="medium",
        title="咖啡偏好",
    )
    fm = _yaml.safe_load(
        (vault / "wiki" / "syntheses" / "咖啡偏好.md")
        .read_text(encoding="utf-8")
        .split("---")[1]
    )
    assert fm["confidence"] == "medium"
    assert fm["last_modified_by"] == "user"


# -----------------------------------------------------------------------------
# Task 8 — lark_doc / lark_sheet / lark_minutes URL parsers
# -----------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402


def test_lark_doc_parser_handles_docx_url() -> None:
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.lark_doc import LarkDocParser

    fi = FeedInput(
        raw_arg="https://example.larkoffice.com/docx/doxcnXXXXXXXXXXXX",
        is_url=True,
    )
    assert LarkDocParser().can_handle(fi) is True


def test_lark_doc_parser_does_not_handle_sheet_url() -> None:
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.lark_doc import LarkDocParser

    fi = FeedInput(
        raw_arg="https://example.larkoffice.com/sheets/shtcnXXXXXXXXXXXX",
        is_url=True,
    )
    assert LarkDocParser().can_handle(fi) is False


def test_lark_doc_parser_invokes_lark_cli_with_profile(tmp_path: Path) -> None:
    """Codex round 1 Finding 8: lark parsers must pass profile= and consume
    the JSON `markdown` field, matching M2 adapters/docs_owned.py."""
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.lark_doc import LarkDocParser

    fi = FeedInput(
        raw_arg="https://example.larkoffice.com/docx/doxcnXXXXXXXXXXXX",
        is_url=True,
    )
    with patch(
        "clonemate.feed_parsers.lark_doc.lark_cli.run",
        return_value={"markdown": "# fetched markdown\n"},
    ) as m:
        raws = LarkDocParser().parse_with_profile(fi, profile="claude-code")
    m.assert_called_once()
    # Verify profile= was passed
    _args, kwargs = m.call_args
    assert kwargs.get("profile") == "claude-code"
    assert raws and "fetched markdown" in raws[0].content


def test_lark_doc_parser_parse_without_profile_raises(tmp_path: Path) -> None:
    """Direct .parse() without profile raises (lark needs auth)."""
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.lark_doc import LarkDocParser

    fi = FeedInput(
        raw_arg="https://example.larkoffice.com/docx/doxcnXXXXXXXXXXXX",
        is_url=True,
    )
    with pytest.raises(RuntimeError, match="profile"):
        LarkDocParser().parse(fi)


def test_lark_sheet_parser_handles_sheet_url_and_invokes_cli() -> None:
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.lark_sheet import LarkSheetParser

    fi = FeedInput(
        raw_arg="https://example.larkoffice.com/sheets/shtcnXXXXXXXXXXXX",
        is_url=True,
    )
    p = LarkSheetParser()
    assert p.can_handle(fi) is True
    with patch(
        "clonemate.feed_parsers.lark_sheet.lark_cli.run",
        return_value={"csv": "a,b\n1,2\n"},
    ) as m:
        raws = p.parse_with_profile(fi, profile="claude-code")
    _args, kwargs = m.call_args
    assert kwargs.get("profile") == "claude-code"
    assert raws and "1,2" in raws[0].content


def test_lark_minutes_parser_handles_minutes_url_and_invokes_cli() -> None:
    from clonemate.feed_parsers._base import FeedInput
    from clonemate.feed_parsers.lark_minutes import LarkMinutesParser

    fi = FeedInput(
        raw_arg="https://example.larkoffice.com/minutes/mmXXXXXXXXXXXX",
        is_url=True,
    )
    p = LarkMinutesParser()
    assert p.can_handle(fi) is True
    with patch(
        "clonemate.feed_parsers.lark_minutes.lark_cli.run",
        return_value={"markdown": "# minute summary\n"},
    ) as m:
        raws = p.parse_with_profile(fi, profile="claude-code")
    _args, kwargs = m.call_args
    assert kwargs.get("profile") == "claude-code"
    assert raws and "minute summary" in raws[0].content


# -----------------------------------------------------------------------------
# Task 9 — extras-gated parsers (pdf / docx / pptx / html)
# -----------------------------------------------------------------------------


def test_pdf_parser_skipped_if_pypdf_missing() -> None:
    """If pypdf isn't installed, the pdf parser is not in the registry.
    If pypdf IS installed, this test skips (the negative case can't be
    exercised without uninstalling the dep)."""
    try:
        import pypdf  # noqa: F401

        pytest.skip("pypdf installed; cannot test missing-extras path")
    except ImportError:
        names = [p.name for p in feed_parsers.list_parsers()]
        assert "pdf" not in names
