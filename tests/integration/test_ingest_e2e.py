"""Python plumbing e2e for ingest — runs in CI (no real LLM).

Strategy: simulate the LLM/subagent layer with deterministic Python that calls
merge_note exactly as the workflow doc prescribes. This verifies:
  - clonemate.ingest_cmd.emit_prompt runs
  - merge_note correctly writes persona / voice / entity pages
  - voice red-line accepts allowed sources, rejects docs
  - sources union across two simulated subagents writing the same entity
  - pinned_fields carry-forward across re-ingest
  - finish() rebuilds index.md and appends log.md
  - re-running ingest is idempotent (no torn pages, sources only grow)
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml
from clonemate import ingest_cmd, merge_note

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "vaults" / "m3-fixture"


def _copy_fixture(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    shutil.copytree(_FIXTURE, vault)
    return vault


def _git_init(vault: Path) -> None:
    """Init git in the vault so `ingest_cmd.finish` can auto-commit.

    Codex round 3 Finding 9 made finish() auto-commit; the fixture isn't a git
    repo by default, so any test exercising finish must seed a real git repo.
    """
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )


def _fake_subagent_dispatch(vault: Path, *, target_open_id: str) -> int:
    """Stand-in for Claude main conversation + subagents.

    Reads raw frontmatter, then emits exactly what the workflow doc promises:
      - persona from contact + im_1v1
      - voice from im_1v1 (author == target only)
      - entity for the chat itself
    Returns the count of wiki pages written.
    """
    written = 0

    # sub-A equivalent: persona from contact source
    contact_files = list((vault / "raw" / "contact").glob("profile-*.md"))
    if contact_files:
        # Read the contact src_id from frontmatter
        text = contact_files[0].read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---")[1])
        src = fm["src_id"]
        merge_note.write(
            vault_dir=vault, page_type="persona", title=None,
            sources=[src], confidence="medium",
            body="# 张三\n\n## 职责\n后端 + AI infra\n\n## 部门\nY 团队\n",
            author_role="ingest",
        )
        written += 1

    # sub-B equivalent: voice from im_1v1 (author == target only)
    im_files = list((vault / "raw" / "im_1v1").rglob("*-*.md"))
    if im_files:
        text = im_files[0].read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---")[1])
        src = fm["src_id"]
        # voice red-line: must pass target_open_id + voice_evidence with author==target
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=[src],
            source_types_map={src: fm["source_type"]},
            target_open_id=target_open_id,
            voice_evidence=[
                {"src_id": src, "author_open_id": target_open_id,
                 "quote": "嗯,我看了一下,这块我有个不同看法"},
            ],
            confidence="low",  # only one source — needs more
            needs_review=True,
            body=(
                "## 总体基调\n\n简洁 / 偏理性\n\n"
                "## 句式特征\n\n- 开场:\"嗯,我看了一下\"\n"
                "- 异议:\"这块我有个不同看法\"\n"
                "\n## 高频口头禅\n\n- \"这块\"\n"
                "\n## 不会出现的表达\n\n(待更多 raw)\n"
                "\n## 场景分段 few-shot\n\n### §1v1 场景\n(待更多 raw)\n"
            ),
            author_role="ingest",
        )
        written += 1

    # sub-C equivalent: entity for the IM partner / chat
    if im_files:
        merge_note.write(
            vault_dir=vault, page_type="entity", title="李四",
            sources=[src], confidence="low", needs_review=True,
            body="# 李四\n\n## 协作画像\n张三的 1v1 对话伙伴\n",
            author_role="ingest",
        )
        written += 1

    return written


def test_ingest_pipeline_writes_persona_voice_and_entity(tmp_path: Path) -> None:
    """Exercise emit_prompt → fake subagents → finish on the m3-fixture vault."""
    vault = _copy_fixture(tmp_path)
    _git_init(vault)
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))

    # Step 1: emit_prompt (Python orchestrator part — does NOT invoke LLM)
    prompt = ingest_cmd.emit_prompt(vault)
    assert "ou_xxxxxxxxxxxxxxxx" in prompt
    assert "references/prompt-ingest.md" in prompt

    # Step 2: simulate Claude main conversation + subagents
    wiki_count = _fake_subagent_dispatch(vault, target_open_id=cy["identity"]["open_id"])
    assert wiki_count == 3

    # Step 3: finish — rebuild index, append log
    ingest_cmd.finish(vault, raw_count=2, wiki_count=wiki_count)

    # Assertions on final state
    assert (vault / "wiki" / "persona.md").is_file()
    assert (vault / "wiki" / "voice.md").is_file()
    assert (vault / "wiki" / "entities" / "李四.md").is_file()
    assert (vault / "index.md").is_file()
    assert (vault / "log.md").is_file()

    # Index has all required buckets and references the wiki pages
    index = (vault / "index.md").read_text(encoding="utf-8")
    assert "Persona" in index
    assert "Voice" in index
    assert "Entities" in index
    assert "wiki/persona.md" in index
    assert "wiki/voice.md" in index
    assert "wiki/entities/李四.md" in index

    # Log has ingest entry
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "+2 raw / +3 wiki" in log


def test_ingest_voice_red_line_rejects_docs_source(tmp_path: Path) -> None:
    """A subagent trying to attribute voice to a docs src must be rejected."""
    vault = _copy_fixture(tmp_path)
    import pytest as _pt
    with _pt.raises(merge_note.VoiceSourceViolation):
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-fake-docs"],
            source_types_map={"src-fake-docs": "docs"},
            confidence="medium", body="## 总体基调\n",
            author_role="ingest",
        )


def test_ingest_idempotent_re_run_grows_sources(tmp_path: Path) -> None:
    """Re-running ingest on the same vault must NOT lose sources from the
    first run; the sources list grows or stays the same — never shrinks."""
    vault = _copy_fixture(tmp_path)
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))

    _fake_subagent_dispatch(vault, target_open_id=cy["identity"]["open_id"])
    persona_after_first = yaml.safe_load(
        (vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1]
    )
    sources_first = set(persona_after_first["sources"])
    assert sources_first  # not empty

    # Re-run (simulating second `clonemate ingest`)
    _fake_subagent_dispatch(vault, target_open_id=cy["identity"]["open_id"])
    persona_after_second = yaml.safe_load(
        (vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1]
    )
    sources_second = set(persona_after_second["sources"])

    # Sources only grow (or stay the same); never shrink
    assert sources_first.issubset(sources_second)


def test_ingest_pinned_fields_survive_re_ingest_without_caller_help(tmp_path: Path) -> None:
    """Codex Finding 2 e2e: user pins persona's 职责; re-ingest WITHOUT caller
    passing pinned_fields must preserve both the pin and the body section."""
    vault = _copy_fixture(tmp_path)
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))

    _fake_subagent_dispatch(vault, target_open_id=cy["identity"]["open_id"])
    # User reviews and pins the 职责 field
    merge_note.pin(vault_dir=vault, page_type="persona", title=None, field="职责")

    # Capture the 职责 section
    persona_before = (vault / "wiki" / "persona.md").read_text(encoding="utf-8")
    assert "## 职责" in persona_before

    # Re-run ingest — fake subagent does NOT pass pinned_fields anywhere
    _fake_subagent_dispatch(vault, target_open_id=cy["identity"]["open_id"])

    persona_after = (vault / "wiki" / "persona.md").read_text(encoding="utf-8")
    fm = yaml.safe_load(persona_after.split("---")[1])
    assert "职责" in fm["pinned_fields"], "pin lost across re-ingest"
    # 职责 H2 section preserved verbatim
    assert "后端 + AI infra" in persona_after, "pinned section content lost"


def test_ingest_voice_rejects_non_target_quote_e2e(tmp_path: Path) -> None:
    """Codex Finding 9 e2e: a fake subagent attempting to attribute a non-target
    author's quote to voice.md MUST be rejected at write time, not after the
    fact by lint or human review."""
    import pytest as _pt
    vault = _copy_fixture(tmp_path)
    cy = yaml.safe_load((vault / "_clone.yaml").read_text(encoding="utf-8"))
    target_oid = cy["identity"]["open_id"]
    other_oid = "ou_yyyyyyyyyyyyyyyy"  # sanitize: allow-line test fixture

    im_files = list((vault / "raw" / "im_1v1").rglob("*-*.md"))
    src = yaml.safe_load(im_files[0].read_text(encoding="utf-8").split("---")[1])["src_id"]

    with _pt.raises(merge_note.VoiceSourceViolation):
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=[src],
            source_types_map={src: "im_group"},
            target_open_id=target_oid,
            voice_evidence=[
                # subagent claims this is a target quote, but author is someone else.
                {"src_id": src, "author_open_id": other_oid, "quote": "他人的话"},
            ],
            confidence="medium", body="## 总体基调\n",
            author_role="ingest",
        )


def test_ingest_disjoint_section_writes_preserve_both(tmp_path: Path) -> None:
    """Codex Finding 8 e2e: subagent C writes entity body 概述; subagent D
    later writes 协作画像 (disjoint H2). Final entity page contains both."""
    vault = _copy_fixture(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-A"], confidence="medium",
        body="# XX 项目\n\n## 概述\nsub-C 写的概述\n",
        author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-B"], confidence="medium",
        body="# XX 项目\n\n## 协作画像\nsub-D 写的协作\n",
        author_role="ingest",
    )
    text = (vault / "wiki" / "entities" / "XX 项目.md").read_text(encoding="utf-8")
    assert "sub-C 写的概述" in text
    assert "sub-D 写的协作" in text
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["sources"] == ["src-A", "src-B"]


def test_ingest_extra_frontmatter_cannot_override_sources(tmp_path: Path) -> None:
    """Codex Finding 6 e2e: a subagent trying to bypass sources via
    extra_frontmatter is rejected."""
    import pytest as _pt
    vault = _copy_fixture(tmp_path)
    with _pt.raises(merge_note.FrontmatterExtraKeyError):
        merge_note.write(
            vault_dir=vault, page_type="entity", title="X",
            sources=["src-real"], confidence="high", body="# X\n",
            author_role="ingest",
            extra_frontmatter={"sources": ["src-fake"]},
        )
