"""Tests for merge_note.py — wiki single-writer entry-point."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from clonemate import merge_note


def _vault(tmp_path: Path) -> Path:
    v = tmp_path / "zhangsan"
    (v / "wiki" / "entities").mkdir(parents=True)
    (v / "wiki" / "concepts").mkdir(parents=True)
    (v / "wiki" / "syntheses").mkdir(parents=True)
    (v / "wiki" / "sources").mkdir(parents=True)
    return v


def test_write_creates_new_page(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = merge_note.write(
        vault_dir=vault,
        page_type="entity",
        title="XX 项目",
        sources=["src-0001"],
        confidence="medium",
        body="# XX 项目\n\n张三主导设计。\n",
        author_role="ingest",
    )
    assert result.path == vault / "wiki" / "entities" / "XX 项目.md"
    assert result.created is True
    text = result.path.read_text(encoding="utf-8")
    fm_start = text.index("---") + 3
    fm_end = text.index("---", fm_start)
    fm = yaml.safe_load(text[fm_start:fm_end])
    assert fm["page_type"] == "entity"
    assert fm["sources"] == ["src-0001"]
    assert fm["confidence"] == "medium"
    assert fm["needs_review"] is False
    assert fm["pinned_fields"] == []
    assert fm["last_modified_by"] == "ingest"
    assert "last_modified" in fm
    assert "# XX 项目" in text


# ---------------------------------------------------------------------------
# Task 5: frontmatter validation — invalid page_type / confidence / role
# ---------------------------------------------------------------------------


def test_unknown_page_type_raises(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with pytest.raises(ValueError) as exc:
        merge_note.write(
            vault_dir=vault, page_type="bogus", title="x", sources=[],
            confidence="high", body="x", author_role="ingest",
        )
    assert "page_type" in str(exc.value)


def test_invalid_confidence_raises(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with pytest.raises(ValueError) as exc:
        merge_note.write(
            vault_dir=vault, page_type="entity", title="x", sources=[],
            confidence="excellent", body="x", author_role="ingest",
        )
    assert "confidence" in str(exc.value)


def test_invalid_author_role_raises(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with pytest.raises(ValueError) as exc:
        merge_note.write(
            vault_dir=vault, page_type="entity", title="x", sources=[],
            confidence="high", body="x", author_role="bot",
        )
    assert "author_role" in str(exc.value)


def test_persona_omits_title_in_frontmatter(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=[],
        confidence="medium", body="# 张三\n", author_role="ingest",
    )
    text = result.path.read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---")[1])
    assert "title" not in fm


@pytest.mark.parametrize(
    "title",
    [
        "../escaped",
        "..",
        "/abs/path",
        "wiki/../../../etc/passwd",
        "concept/sub-page",   # subdirectory not allowed
        "evil\\backslash",
        "",
        "...",
    ],
)
def test_unsafe_titles_rejected(tmp_path: Path, title: str) -> None:
    """Codex Finding 5: LLM-derived titles must not be able to escape wiki/<subtype>/."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.TitleUnsafeError):
        merge_note.write(
            vault_dir=vault, page_type="entity", title=title,
            sources=[], confidence="high",
            body="# x\n", author_role="ingest",
        )


def test_safe_title_lands_under_expected_dir(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=[], confidence="high",
        body="# x\n", author_role="ingest",
    )
    # Resolved path must be a child of vault/wiki/entities/
    expected = (vault / "wiki" / "entities").resolve()
    assert result.path.resolve().parent == expected


@pytest.mark.parametrize(
    "evil_key",
    ["sources", "page_type", "pinned_fields", "confidence",
     "last_modified_by", "needs_review", "title", "last_modified",
     "voice_evidence",
     # Codex Finding 12: arbitrary unknown keys also rejected (allow-list, not blocklist)
     "origin", "secret", "_meta", "owner",
     ],
)
def test_extra_frontmatter_non_allowlisted_keys_rejected(tmp_path: Path, evil_key: str) -> None:
    """Codex Findings 6+12: extra_frontmatter is an allow-list. Any key NOT
    in _ALLOWED_EXTRA_FRONTMATTER is rejected — covers reserved invariants
    AND arbitrary schema-drift attempts."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.FrontmatterExtraKeyError):
        merge_note.write(
            vault_dir=vault, page_type="entity", title="X",
            sources=[], confidence="high", body="# X\n",
            author_role="ingest",
            extra_frontmatter={evil_key: "evil"},
        )


def test_extra_frontmatter_allowlist_with_type_check(tmp_path: Path) -> None:
    """Allow-listed key with correct type passes; wrong type rejected."""
    vault = _vault(tmp_path)
    result = merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=[], confidence="high", body="# X\n",
        author_role="ingest",
        extra_frontmatter={"few_shot_count": 7},
    )
    fm = yaml.safe_load(result.path.read_text(encoding="utf-8").split("---")[1])
    assert fm["few_shot_count"] == 7

    # Wrong type (string instead of int) rejected
    with pytest.raises(merge_note.FrontmatterExtraKeyError):
        merge_note.write(
            vault_dir=vault, page_type="entity", title="Y",
            sources=[], confidence="high", body="# Y\n",
            author_role="ingest",
            extra_frontmatter={"few_shot_count": "7"},
        )


# ---------------------------------------------------------------------------
# Task 6: pinned_fields — carry-forward (Codex Finding 2)
# ---------------------------------------------------------------------------


def test_pinned_fields_preserve_body_section_on_first_pin(tmp_path: Path) -> None:
    """First write with explicit pinned_fields=["职责"] establishes the pin."""
    vault = _vault(tmp_path)
    body_v1 = "# 张三\n\n## 职责\n后端 + AI infra(用户已确认)\n\n## 专长\n(初版猜的)\n"
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=["src-0001"],
        confidence="high", body=body_v1, author_role="user",
        pinned_fields=["职责"],
    )
    # A second write *with* the same pin still preserves
    body_v2 = "# 张三\n\n## 职责\n推断:模糊后端\n\n## 专长\nGo / Python\n"
    result = merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=["src-0007"],
        confidence="medium", body=body_v2, author_role="ingest",
        pinned_fields=["职责"],
    )
    text = result.path.read_text(encoding="utf-8")
    assert "后端 + AI infra(用户已确认)" in text
    assert "推断:模糊后端" not in text
    assert "Go / Python" in text
    assert "职责" in result.pinned_preserved


def test_pinned_carry_forward_when_caller_omits(tmp_path: Path) -> None:
    """Codex Finding 2: re-ingest WITHOUT passing pinned_fields must NOT clear pins.

    Sequence:
      1. ingest writes page with pinned_fields=[] (initial)
      2. user pins "职责" via merge_note.pin()
      3. another ingest call writes the page WITHOUT pinned_fields kwarg
      4. assert pin AND its body section survive (default carry-forward)
    """
    vault = _vault(tmp_path)
    # 1. initial ingest
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=["src-0001"],
        confidence="medium",
        body="# 张三\n\n## 职责\n用户后来手工填写\n\n## 专长\n初版\n",
        author_role="ingest",
        # NOTE: no pinned_fields argument
    )
    # 2. user pins
    merge_note.pin(vault_dir=vault, page_type="persona", title=None, field="职责")

    # 3. Re-ingest WITHOUT pinned_fields — caller does NOT remember to pass it.
    result = merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=["src-0007"],
        confidence="medium",
        body="# 张三\n\n## 职责\n模型重新猜:可能是 PM\n\n## 专长\nGo / Python\n",
        author_role="ingest",
        # CRITICAL: pinned_fields not passed → must carry forward existing
    )

    # 4. Assert the pin AND its body section both survived
    text = result.path.read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---")[1])
    assert "职责" in fm["pinned_fields"], "pin must be carried forward when caller omits pinned_fields"
    assert "用户后来手工填写" in text, "pinned section body must survive"
    assert "模型重新猜:可能是 PM" not in text, "new body for pinned section must NOT clobber"
    # Non-pinned section advances normally
    assert "Go / Python" in text
    assert "职责" in result.pinned_preserved


def test_explicit_empty_pinned_does_not_clear_existing_pin(tmp_path: Path) -> None:
    """Even if caller passes pinned_fields=[] explicitly on UPDATE, existing pins stay.

    Rationale: only `pin()` / `unpin()` should mutate the pin list. write() is for
    content; trying to use write() to clear pins is a usage error and we silently
    protect the user.
    """
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=[], confidence="low",
        body="# x\n## 职责\n初版\n", author_role="ingest", pinned_fields=["职责"],
    )
    # update with explicit empty list
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=[], confidence="low",
        body="# x\n## 职责\n试图清掉\n", author_role="ingest", pinned_fields=[],
    )
    fm = yaml.safe_load((vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1])
    assert fm["pinned_fields"] == ["职责"]


def test_pinned_section_carried_forward_when_new_body_omits_h2(tmp_path: Path) -> None:
    """Codex Finding 7: if re-ingest output omits the pinned H2 entirely, the
    pinned section body MUST still survive — pin guarantees data preservation
    regardless of what the new body says."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=["src-0001"],
        confidence="medium",
        body="# 张三\n\n## 职责\n后端 + AI infra(用户已确认)\n\n## 专长\n初版\n",
        author_role="ingest", pinned_fields=["职责"],
    )
    # Re-ingest with a body that DOESN'T include `## 职责` heading at all.
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None, sources=["src-0007"],
        confidence="medium",
        body="# 张三\n\n## 专长\nGo / Python\n\n## 沟通偏好\n直接\n",
        author_role="ingest",
    )
    text = (vault / "wiki" / "persona.md").read_text(encoding="utf-8")
    # Pinned section content survived (carried forward from old)
    assert "后端 + AI infra(用户已确认)" in text
    # New non-pinned sections also present
    assert "Go / Python" in text
    assert "直接" in text
    # Pin still in frontmatter
    fm = yaml.safe_load(text.split("---")[1])
    assert "职责" in fm["pinned_fields"]


def test_old_non_pinned_section_carried_forward_when_new_body_omits_it(tmp_path: Path) -> None:
    """Codex Finding 8: subagent C writes section X; subagent D writes section Y.
    Without code-level body merge, D's body would clobber X. We must preserve X."""
    vault = _vault(tmp_path)
    # subagent C writes
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-0007"], confidence="medium",
        body="# XX 项目\n\n## 概述\n来自 sub-C 的概述\n",
        author_role="ingest",
    )
    # subagent D writes a DIFFERENT section (no overlap with C's heading)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-0019"], confidence="medium",
        body="# XX 项目\n\n## 协作画像\n来自 sub-D 的协作\n",
        author_role="ingest",
    )
    text = (vault / "wiki" / "entities" / "XX 项目.md").read_text(encoding="utf-8")
    assert "来自 sub-C 的概述" in text, "sub-C's section was clobbered"
    assert "来自 sub-D 的协作" in text, "sub-D's section missing"


def test_same_section_in_both_yields_conflict_marker(tmp_path: Path) -> None:
    """If two writers (or two ingest passes) hit the same H2 section, new wins
    but a `> ⚠️ CONFLICT` marker is injected so lint/review can surface it."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0007"], confidence="medium",
        body="# X\n\n## 概述\nv1 内容\n",
        author_role="ingest",
    )
    result = merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0019"], confidence="medium",
        body="# X\n\n## 概述\nv2 内容(覆盖)\n",
        author_role="ingest",
    )
    text = result.path.read_text(encoding="utf-8")
    assert "v2 内容(覆盖)" in text
    assert "⚠️ CONFLICT" in text
    assert "概述" in result.conflicts
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["needs_review"] is True


def test_h1_page_title_does_not_trigger_false_conflict(tmp_path: Path) -> None:
    """Codex Finding 14 (round 4): every wiki page starts with `# Title` H1.
    `_SECTION_RE` is H2-only so the H1 page title is preamble — repeated
    re-ingest with the same H1 title does NOT trigger a CONFLICT marker on
    disjoint H2 edits."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-A"], confidence="medium",
        body="# XX 项目\n\n## 概述\n初始概述\n",
        author_role="ingest",
    )
    result = merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-B"], confidence="medium",
        body="# XX 项目\n\n## 协作画像\n后续协作\n",
        author_role="ingest",
    )
    text = result.path.read_text(encoding="utf-8")
    # Both H2 sections present (carry-forward + new)
    assert "初始概述" in text
    assert "后续协作" in text
    # No conflict marker — disjoint edits don't clash
    assert "⚠️ CONFLICT" not in text
    assert result.conflicts == []
    # needs_review remains caller-controlled (not auto-set due to false conflict)
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["needs_review"] is False


# ---------------------------------------------------------------------------
# Task 7: voice red-line tests (Codex Finding 1)
# ---------------------------------------------------------------------------

_TARGET_OID = "ou_xxxxxxxxxxxxxxxx"  # sanitize: allow-line test fixture


def _voice_kwargs_minimum(*, sources, source_types, evidence):
    """Helper: build the minimum-required kwargs for a successful voice write."""
    return dict(
        sources=sources,
        source_types_map=source_types,
        target_open_id=_TARGET_OID,
        voice_evidence=evidence,
    )


def test_voice_rejects_docs_source_type(tmp_path: Path) -> None:
    """spec §8.5: voice sources can only be im_1v1 / im_group / minutes / doc_comments."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            **_voice_kwargs_minimum(
                sources=["src-0007"],
                source_types={"src-0007": "docs"},
                evidence=[{"src_id": "src-0007", "author_open_id": _TARGET_OID, "quote": "x"}],
            ),
            confidence="medium", body="## 总体基调\n", author_role="ingest",
        )
    assert "src-0007" in str(exc.value) and "docs" in str(exc.value)


def test_voice_requires_source_types_map(tmp_path: Path) -> None:
    """Codex Finding 1: missing source_types_map MUST raise (not silently skip)."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-0001"],
            target_open_id=_TARGET_OID,
            voice_evidence=[{"src_id": "src-0001", "author_open_id": _TARGET_OID, "quote": "x"}],
            confidence="medium", body="## 总体基调\n", author_role="ingest",
        )
    assert "source_types_map" in str(exc.value)


def test_voice_requires_target_open_id(tmp_path: Path) -> None:
    """Codex Finding 9: voice writes need target_open_id to validate authors."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-0001"],
            source_types_map={"src-0001": "im_1v1"},
            voice_evidence=[{"src_id": "src-0001", "author_open_id": _TARGET_OID, "quote": "x"}],
            confidence="medium", body="## 总体基调\n", author_role="ingest",
        )
    assert "target_open_id" in str(exc.value)


def test_voice_requires_evidence(tmp_path: Path) -> None:
    """Codex Finding 9: source_type alone is not enough — voice_evidence with
    per-quote author_open_id is required."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-0001"],
            source_types_map={"src-0001": "im_1v1"},
            target_open_id=_TARGET_OID,
            # voice_evidence omitted
            confidence="medium", body="## 总体基调\n", author_role="ingest",
        )
    assert "voice_evidence" in str(exc.value)


def test_voice_empty_evidence_list_rejected(tmp_path: Path) -> None:
    """Codex Finding 13 (round 4): voice_evidence=[] also rejected — caller
    cannot bypass red-line by passing empty list."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-0001"],
            source_types_map={"src-0001": "im_1v1"},
            target_open_id=_TARGET_OID,
            voice_evidence=[],   # empty list ≠ None, both must reject
            confidence="medium", body="## 总体基调\n", author_role="ingest",
        )
    assert "non-empty" in str(exc.value).lower() or "voice_evidence" in str(exc.value)


def test_voice_rejects_non_target_author_in_evidence(tmp_path: Path) -> None:
    """Codex Finding 9: even within an allowed source_type (im_group), a quote
    by a non-target author MUST be rejected."""
    vault = _vault(tmp_path)
    other_oid = "ou_yyyyyyyyyyyyyyyy"  # sanitize: allow-line test fixture
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-0007"],
            source_types_map={"src-0007": "im_group"},
            target_open_id=_TARGET_OID,
            voice_evidence=[
                {"src_id": "src-0007", "author_open_id": other_oid, "quote": "他人的话"},
            ],
            confidence="medium", body="## 总体基调\n", author_role="ingest",
        )
    assert "author_open_id" in str(exc.value)
    assert "non-target" in str(exc.value).lower() or "spec" in str(exc.value)


def test_voice_evidence_missing_keys_rejected(tmp_path: Path) -> None:
    """Each evidence entry must have src_id + author_open_id + quote."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-0001"],
            source_types_map={"src-0001": "im_1v1"},
            target_open_id=_TARGET_OID,
            voice_evidence=[{"src_id": "src-0001", "quote": "missing author"}],
            confidence="medium", body="## 总体基调\n", author_role="ingest",
        )
    assert "author_open_id" in str(exc.value)


def test_voice_empty_sources_template_allowed(tmp_path: Path) -> None:
    """Initial / template voice page with sources=[] needs no map / target / evidence."""
    vault = _vault(tmp_path)
    result = merge_note.write(
        vault_dir=vault, page_type="voice", title=None,
        sources=[],
        confidence="low", body="## 总体基调\n(待 ingest)\n",
        author_role="ingest", needs_review=True,
    )
    assert result.created is True


def test_voice_accepts_full_red_line_compliance(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = merge_note.write(
        vault_dir=vault, page_type="voice", title=None,
        sources=["src-0001", "src-0007"],
        source_types_map={"src-0001": "im_1v1", "src-0007": "minutes"},
        target_open_id=_TARGET_OID,
        voice_evidence=[
            {"src_id": "src-0001", "author_open_id": _TARGET_OID, "quote": "嗯,我看了一下"},
            {"src_id": "src-0007", "author_open_id": _TARGET_OID, "quote": "本质上"},
        ],
        confidence="medium", body="## 总体基调\n",
        author_role="ingest",
    )
    assert result.created is True
    fm = yaml.safe_load(result.path.read_text(encoding="utf-8").split("---")[1])
    assert fm["voice_evidence"][0]["author_open_id"] == _TARGET_OID


def test_non_voice_pages_dont_need_evidence_map(tmp_path: Path) -> None:
    """entity / concept / synthesis pages don't need source_types_map / target / evidence."""
    vault = _vault(tmp_path)
    result = merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-0007"],
        confidence="medium", body="# XX 项目\n",
        author_role="ingest",
    )
    assert result.created is True


def test_voice_body_unmatched_quote_in_fewshot_section_rejected(tmp_path: Path) -> None:
    """Codex Finding 10 (round 3): a cited quote in the few-shot section that
    isn't backed by voice_evidence MUST be rejected — even if all evidence
    entries themselves are author==target compliant."""
    vault = _vault(tmp_path)
    body = (
        "# 总体基调\n简洁\n\n"
        "# 场景分段 few-shot\n\n"
        "## §1v1 场景\n"
        "- (src-fake): \"句子从未在 evidence 里出现\"\n"
    )
    with pytest.raises(merge_note.VoiceSourceViolation) as exc:
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-real"],
            source_types_map={"src-real": "im_1v1"},
            target_open_id=_TARGET_OID,
            voice_evidence=[
                {"src_id": "src-real", "author_open_id": _TARGET_OID, "quote": "compliant"},
            ],
            confidence="medium", body=body,
            author_role="ingest",
        )
    err = str(exc.value)
    assert "src-fake" in err or "voice_evidence" in err


def test_voice_body_quote_must_appear_verbatim_in_evidence(tmp_path: Path) -> None:
    """Even if the cited src_id exists in evidence, the quoted text must be a
    substring of an evidence entry's quote (or matching exactly)."""
    vault = _vault(tmp_path)
    body = (
        "# 场景分段\n\n## §1v1 场景\n"
        "- (src-real): \"完全不同的虚构句子\"\n"
    )
    with pytest.raises(merge_note.VoiceSourceViolation):
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=["src-real"],
            source_types_map={"src-real": "im_1v1"},
            target_open_id=_TARGET_OID,
            voice_evidence=[
                {"src_id": "src-real", "author_open_id": _TARGET_OID,
                 "quote": "嗯,我看了一下"},
            ],
            confidence="medium", body=body,
            author_role="ingest",
        )


def test_voice_body_narrative_text_not_quote_validated(tmp_path: Path) -> None:
    """Narrative sections (总体基调 / 句式特征 etc., NOT containing 场景 / §) are
    free text — list items there don't need to cite src ids."""
    vault = _vault(tmp_path)
    body = (
        "# 总体基调\n\n"
        "- 简洁 / 偏理性\n"
        "- 偶用 emoji\n\n"
        "# 句式特征\n\n"
        "- 开场\"嗯,我看了一下\"\n\n"
        "# 场景分段 few-shot\n\n"
        "## §1v1 场景\n"
        "- (src-real): \"嗯,我看了一下\"\n"
    )
    result = merge_note.write(
        vault_dir=vault, page_type="voice", title=None,
        sources=["src-real"],
        source_types_map={"src-real": "im_1v1"},
        target_open_id=_TARGET_OID,
        voice_evidence=[
            {"src_id": "src-real", "author_open_id": _TARGET_OID,
             "quote": "嗯,我看了一下"},
        ],
        confidence="medium", body=body,
        author_role="ingest",
    )
    assert result.created is True


# ---------------------------------------------------------------------------
# Task 8: concurrent safety + sources union (Codex Finding 3)
# ---------------------------------------------------------------------------

import threading  # noqa: E402


def test_concurrent_writes_serialize_via_flock(tmp_path: Path) -> None:
    """Two threads writing the same page must not produce torn content."""
    vault = _vault(tmp_path)
    errors: list[Exception] = []

    def writer(prefix: str) -> None:
        try:
            body = "# Concurrent\n\n" + "".join(
                f"## {prefix}-{i}\nfrom {prefix} #{i}\n\n" for i in range(50)
            )
            merge_note.write(
                vault_dir=vault, page_type="entity", title="ConcurrentEntity",
                sources=[f"src-{prefix}-001"], confidence="medium", body=body,
                author_role="ingest",
            )
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=writer, args=("A",))
    t2 = threading.Thread(target=writer, args=("B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    target = vault / "wiki" / "entities" / "ConcurrentEntity.md"
    text = target.read_text(encoding="utf-8")
    # Frontmatter+body separator intact (no torn write)
    assert text.count("---") >= 2
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["page_type"] == "entity"
    # CRITICAL: sources MUST be the UNION of both writers' sources, not just
    # the last one. Codex Finding 3.
    assert "src-A-001" in fm["sources"], "concurrent writer A's source lost"
    assert "src-B-001" in fm["sources"], "concurrent writer B's source lost"


def test_sequential_writes_union_sources(tmp_path: Path) -> None:
    """Codex Finding 3: when two subagents sequentially write the same entity
    page, their sources must accumulate (not overwrite). The workflow promise
    that 'later subagents append their sources/content' is enforced in code,
    not just by prompt obedience."""
    vault = _vault(tmp_path)
    # subagent C writes page first
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-0007", "src-0019"], confidence="medium",
        body="# XX 项目\n\n## 概述\n版本 1\n",
        author_role="ingest",
    )
    # subagent D later writes the same page with a different source list
    result = merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-0042"], confidence="medium",
        body="# XX 项目\n\n## 协作画像\nD 视角\n",
        author_role="ingest",
    )
    fm = yaml.safe_load(result.path.read_text(encoding="utf-8").split("---")[1])
    # Sources are the UNION (sorted dedup) — neither writer lost provenance
    assert fm["sources"] == sorted({"src-0007", "src-0019", "src-0042"})


def test_created_flag_correct_inside_lock(tmp_path: Path) -> None:
    """Sequential writers: first sees created=True, second sees created=False.

    spec invariant: existence is determined inside the lock, not before it.
    """
    vault = _vault(tmp_path)
    r1 = merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0001"], confidence="high",
        body="# X\n", author_role="ingest",
    )
    r2 = merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0002"], confidence="high",
        body="# X\n", author_role="ingest",
    )
    assert r1.created is True
    assert r2.created is False


# ---------------------------------------------------------------------------
# Task 9: pin / unpin convenience helpers
# ---------------------------------------------------------------------------


def test_pin_field_adds_to_pinned_list(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=["src-0001"], confidence="medium",
        body="# 张三\n\n## 职责\n后端\n", author_role="ingest",
    )
    merge_note.pin(vault_dir=vault, page_type="persona", title=None, field="职责")
    persona_path = vault / "wiki" / "persona.md"
    fm = yaml.safe_load(persona_path.read_text(encoding="utf-8").split("---")[1])
    assert "职责" in fm["pinned_fields"]


def test_unpin_field(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=[], confidence="low", body="# x\n## 职责\n后端\n",
        author_role="ingest", pinned_fields=["职责"],
    )
    merge_note.unpin(vault_dir=vault, page_type="persona", title=None, field="职责")
    persona_path = vault / "wiki" / "persona.md"
    fm = yaml.safe_load(persona_path.read_text(encoding="utf-8").split("---")[1])
    assert "职责" not in fm["pinned_fields"]


# ---------------------------------------------------------------------------
# Task 8: marker-resolution helpers (M4 — Codex Findings 1+2+3+5+6+7+10+12)
# ---------------------------------------------------------------------------


def test_resolve_conflict_replaces_section_and_drops_marker(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-A", "src-B"], confidence="medium",
        body=(
            "# XX 项目\n\n"
            "## 概述\nv1 草稿\n\n> ⚠️ CONFLICT: section `概述` rewritten by ingest.\n\n"
            "## 协作画像\nD\n"
        ),
        author_role="ingest",
    )
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="XX 项目",
        section_name="概述",
        accepted_body="v1 草稿(用户裁决)\n",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "XX 项目.md").read_text(encoding="utf-8")
    assert "⚠️ CONFLICT" not in text
    assert "v1 草稿(用户裁决)" in text
    assert "## 协作画像" in text
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["last_modified_by"] == "user"


def test_resolve_conflict_normalises_missing_trailing_newline(tmp_path: Path) -> None:
    """Codex Finding 2: accepted_body without trailing \\n must NOT glue to next H2."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=[], confidence="medium",
        body="# X\n\n## 概述\nv1\n\n> ⚠️ CONFLICT: x\n\n## 后续\n后续内容\n",
        author_role="ingest",
    )
    # Caller passes body WITHOUT trailing newline (typical user input)
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="X",
        section_name="概述",
        accepted_body="用户输入没换行结尾",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8")
    # Subsequent H2 must remain on its own line
    assert "用户输入没换行结尾" in text
    assert "用户输入没换行结尾## 后续" not in text   # NOT glued
    assert "## 后续" in text
    assert "后续内容" in text


def test_resolve_conflict_clears_needs_review_when_no_markers_remain(tmp_path: Path) -> None:
    """Codex Finding 3: after resolving the LAST marker, needs_review must
    flip to False, not get stuck at the M3-set True."""
    vault = _vault(tmp_path)
    # M3-style write: single conflict, M3 sets needs_review=True
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-A"], confidence="medium",
        body="# X\n\n## 概述\nv1\n\n> ⚠️ CONFLICT: x\n",
        author_role="ingest", needs_review=True,
    )
    fm0 = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm0["needs_review"] is True   # baseline

    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="X",
        section_name="概述",
        accepted_body="resolved\n",
        decided_by_user=True,
    )
    fm1 = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    # No markers remain + confidence != low → needs_review False
    assert fm1["needs_review"] is False


def test_resolve_conflict_keeps_needs_review_when_other_marker_remains(tmp_path: Path) -> None:
    """If conflict resolved but ambiguity / unclear / second conflict still present,
    needs_review stays True."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-A"], confidence="medium",
        body=(
            "# X\n\n"
            "## 概述\nv1\n\n> ⚠️ CONFLICT: x\n\n"
            "## 协作画像\n他人视角\n\n> ⚠️ AMBIGUOUS: X 项目可能是两个东西\n"
        ),
        author_role="ingest",
    )
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="X",
        section_name="概述",
        accepted_body="resolved\n",
        decided_by_user=True,
    )
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["needs_review"] is True   # ambiguity still present


def test_resolve_conflict_raises_when_section_missing(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=[], confidence="medium",
        body="# X\n\n## 概述\nx\n", author_role="ingest",
    )
    with pytest.raises(ValueError) as exc:
        merge_note.resolve_conflict(
            vault_dir=vault, page_type="entity", title="X",
            section_name="不存在",
            accepted_body="任何\n",
            decided_by_user=True,
        )
    assert "不存在" in str(exc.value) or "section" in str(exc.value).lower()


# Codex Finding 1: ambiguity / unclear must also have explicit close paths


def test_resolve_ambiguity_removes_marker_line(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-A"], confidence="medium",
        body=(
            "# X\n\n## 概述\n描述\n\n"
            "> ⚠️ AMBIGUOUS: X 项目可能指 X-service 或开源 X\n\n"
            "## 后续\n后续内容\n"
        ),
        author_role="ingest", needs_review=True,
    )
    merge_note.resolve_ambiguity(
        vault_dir=vault, page_type="entity", title="X",
        marker_text_substring="X-service",
        replacement="它指代码库中的 X-service(用户裁决)",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8")
    assert "⚠️ AMBIGUOUS" not in text
    assert "X-service(用户裁决)" in text
    assert "## 后续" in text
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["needs_review"] is False   # last marker cleared


def test_resolve_ambiguity_with_empty_replacement_just_drops_marker(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-A"], confidence="medium",
        body="# X\n\n> ⚠️ AMBIGUOUS: foo\n\n后文\n",
        author_role="ingest", needs_review=True,
    )
    merge_note.resolve_ambiguity(
        vault_dir=vault, page_type="entity", title="X",
        marker_text_substring="foo",
        replacement="",   # user said "just drop"
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8")
    assert "⚠️ AMBIGUOUS" not in text
    assert "后文" in text


def test_resolve_unclear_removes_marker_line(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="concept", title="RAG",
        sources=["src-A"], confidence="low",
        body="# RAG\n\n> ⚠️ UNCLEAR: ta 立场未明\n",
        author_role="ingest", needs_review=True,
    )
    merge_note.resolve_unclear(
        vault_dir=vault, page_type="concept", title="RAG",
        marker_text_substring="立场未明",
        replacement="ta 倾向先做最简版本验证(用户补充)",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "concepts" / "RAG.md").read_text(encoding="utf-8")
    assert "⚠️ UNCLEAR" not in text
    assert "倾向先做最简版本验证" in text
    fm = yaml.safe_load(text.split("---")[1])
    # No markers remain BUT confidence is low → caller should explicitly call
    # apply_review_accept to promote confidence and clear needs_review.
    assert fm["needs_review"] is True


def test_resolve_unclear_raises_when_marker_not_found(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="concept", title="X",
        sources=["src-A"], confidence="medium",
        body="# X\n\n## 描述\n无 marker\n",
        author_role="ingest",
    )
    with pytest.raises(ValueError) as exc:
        merge_note.resolve_unclear(
            vault_dir=vault, page_type="concept", title="X",
            marker_text_substring="ghost", replacement="x", decided_by_user=True,
        )
    assert "ghost" in str(exc.value) or "not found" in str(exc.value).lower()


# Codex round 2 regressions


def test_resolve_unclear_low_conf_keeps_needs_review_true(tmp_path: Path) -> None:
    """Codex Finding 5: low-conf page with needs_review=False, after marker
    resolution, MUST get needs_review=True (not silently False), until an
    explicit apply_review_accept(confidence=...) closes it.

    Note: the explicit-close half (apply_review_accept) is exercised in Task 9.
    """
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="concept", title="RAG",
        sources=["src-A"], confidence="low",
        body="# RAG\n\n> ⚠️ UNCLEAR: ta 立场未明\n",
        author_role="ingest",
        needs_review=False,   # set False explicitly to simulate the bug scenario
    )
    merge_note.resolve_unclear(
        vault_dir=vault, page_type="concept", title="RAG",
        marker_text_substring="立场未明",
        replacement="ta 倾向最简版本",
        decided_by_user=True,
    )
    fm = yaml.safe_load(
        (vault / "wiki" / "concepts" / "RAG.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["needs_review"] is True   # Codex Finding 5: forced to True for low-conf


def test_resolve_conflict_preserves_same_section_ambiguity_and_unclear(tmp_path: Path) -> None:
    """Codex Finding 6: resolving a conflict in `## X` must keep AMBIGUOUS /
    UNCLEAR markers that were also inside `## X`."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-A"], confidence="medium",
        body=(
            "# X\n\n"
            "## 概述\n"
            "v1 描述\n\n"
            "> ⚠️ CONFLICT: section `概述` rewritten by ingest.\n\n"
            "> ⚠️ AMBIGUOUS: X 项目可能指 X-service 或开源 X\n\n"
            "> ⚠️ UNCLEAR: 项目当前进度未明\n"
        ),
        author_role="ingest",
    )
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="X",
        section_name="概述",
        accepted_body="resolved description\n",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8")
    # CONFLICT gone
    assert "⚠️ CONFLICT" not in text
    # AMBIGUOUS / UNCLEAR preserved
    assert "⚠️ AMBIGUOUS" in text
    assert "X-service" in text
    assert "⚠️ UNCLEAR" in text
    assert "项目当前进度未明" in text
    # Resolved body present
    assert "resolved description" in text
    # needs_review still True (other markers still present)
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["needs_review"] is True


def test_resolve_ambiguity_multi_match_substring_raises(tmp_path: Path) -> None:
    """Codex Finding 7: substring matching multiple markers must raise rather
    than silently mutate them all."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-A"], confidence="medium",
        body=(
            "# X\n\n"
            "> ⚠️ AMBIGUOUS: X 项目歧义 — 是 X-service 还是开源 X\n\n"
            "> ⚠️ AMBIGUOUS: X 项目还有第二种含义 — 是设计提案 X\n"
        ),
        author_role="ingest",
    )
    with pytest.raises(ValueError) as exc:
        merge_note.resolve_ambiguity(
            vault_dir=vault, page_type="entity", title="X",
            marker_text_substring="X 项目",   # matches BOTH markers
            replacement="dropped",
            decided_by_user=True,
        )
    assert "more than one" in str(exc.value).lower() or "matches" in str(exc.value).lower()


def test_resolve_unclear_multi_match_substring_raises(tmp_path: Path) -> None:
    """Same uniqueness contract for UNCLEAR."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="concept", title="Y",
        sources=["src-A"], confidence="medium",
        body=(
            "# Y\n\n"
            "> ⚠️ UNCLEAR: ta 在 RAG 上立场未明\n\n"
            "> ⚠️ UNCLEAR: ta 在向量库上立场未明\n"
        ),
        author_role="ingest",
    )
    with pytest.raises(ValueError):
        merge_note.resolve_unclear(
            vault_dir=vault, page_type="concept", title="Y",
            marker_text_substring="立场未明",   # matches both
            replacement="dropped",
            decided_by_user=True,
        )


def test_resolve_ambiguity_drops_multi_line_block_atomically(tmp_path: Path) -> None:
    """Codex round 4 Finding 12: when an AMBIGUOUS marker has multi-line `> `
    continuation context (candidates / evidence), resolving it must remove
    the WHOLE block atomically — not just the marker line."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="Z",
        sources=["src-A"], confidence="medium",
        body=(
            "# Z\n\n"
            "## 概述\n描述\n\n"
            "> ⚠️ AMBIGUOUS: Z 项目可能指 X-service 或开源 Z\n"
            "> 候选 1: X-service (src-aa)\n"
            "> 候选 2: 开源 Z (src-bb)\n"
            "> 暂无证据\n\n"
            "## 后续\n后续内容\n"
        ),
        author_role="ingest",
    )
    merge_note.resolve_ambiguity(
        vault_dir=vault, page_type="entity", title="Z",
        marker_text_substring="X-service 或开源 Z",
        replacement="它指 X-service(用户裁决)",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "Z.md").read_text(encoding="utf-8")
    assert "⚠️ AMBIGUOUS" not in text
    # ALL continuation lines also dropped — no stale context left in body
    assert "候选 1: X-service" not in text
    assert "候选 2: 开源 Z" not in text
    assert "暂无证据" not in text
    # Replacement present
    assert "它指 X-service(用户裁决)" in text
    # Disjoint section unchanged
    assert "## 后续" in text and "后续内容" in text


def test_resolve_unclear_drops_multi_line_block_atomically(tmp_path: Path) -> None:
    """Same multi-line block contract for UNCLEAR (Codex round 4 Finding 12)."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="concept", title="RAG",
        sources=["src-A"], confidence="medium",
        body=(
            "# RAG\n\n"
            "> ⚠️ UNCLEAR: ta 在 RAG 上立场未明\n"
            "> 在 5 个 chat 中频繁提到\n"
            "> 但未表态\n\n"
            "正文继续\n"
        ),
        author_role="ingest",
    )
    merge_note.resolve_unclear(
        vault_dir=vault, page_type="concept", title="RAG",
        marker_text_substring="立场未明",
        replacement="ta 倾向最简版本验证(用户补充)",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "concepts" / "RAG.md").read_text(encoding="utf-8")
    assert "⚠️ UNCLEAR" not in text
    assert "在 5 个 chat 中频繁提到" not in text
    assert "但未表态" not in text
    assert "倾向最简版本验证" in text
    assert "正文继续" in text


def test_resolve_conflict_preserves_multi_line_marker_context(tmp_path: Path) -> None:
    """Codex round 3 Finding 10: when a CONFLICT-section also contains an
    AMBIGUOUS marker followed by multi-line context (candidates / evidence),
    that whole block must survive the resolve_conflict overwrite."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-A"], confidence="medium",
        body=(
            "# X\n\n"
            "## 概述\n"
            "v1 描述\n\n"
            "> ⚠️ CONFLICT: section `概述` rewritten by ingest.\n\n"
            "> ⚠️ AMBIGUOUS: X 项目可能指 X-service 也可能指开源 X\n"
            "> 候选 1:代码库内 X-service (src-aa)\n"
            "> 候选 2:开源同名项目 X (src-bb)\n"
            "> 暂无证据偏向哪一个\n\n"
            "## 后续\n"
            "后续内容\n"
        ),
        author_role="ingest",
    )
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="X",
        section_name="概述",
        accepted_body="resolved description\n",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8")
    # CONFLICT marker gone
    assert "⚠️ CONFLICT" not in text
    # New body present
    assert "resolved description" in text
    # AMBIGUOUS marker preserved
    assert "⚠️ AMBIGUOUS" in text
    # ALL multi-line context preserved (this is the regression)
    assert "候选 1:代码库内 X-service (src-aa)" in text
    assert "候选 2:开源同名项目 X (src-bb)" in text
    assert "暂无证据偏向哪一个" in text
    # Disjoint H2 unchanged
    assert "## 后续" in text and "后续内容" in text


# ---------------------------------------------------------------------------
# Task 9: apply_review_accept — frontmatter-only flip used by Phase C [A] 接受
# ---------------------------------------------------------------------------


def test_apply_review_accept_flips_needs_review_false(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=["src-1"], confidence="low", needs_review=True,
        body="# 张三\n\n## 职责\n初版\n", author_role="ingest",
    )
    merge_note.apply_review_accept(
        vault_dir=vault, page_type="persona", title=None,
        confidence="high",   # user-confirmed promotion
    )
    fm = yaml.safe_load((vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1])
    assert fm["needs_review"] is False
    assert fm["confidence"] == "high"
    assert fm["last_modified_by"] == "user"


def test_apply_review_accept_can_pin_fields(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="persona", title=None,
        sources=["src-1"], confidence="medium", needs_review=True,
        body="# 张三\n\n## 职责\n后端\n", author_role="ingest",
    )
    merge_note.apply_review_accept(
        vault_dir=vault, page_type="persona", title=None,
        confidence="high", pin_fields=["职责"],
    )
    fm = yaml.safe_load((vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1])
    assert "职责" in fm["pinned_fields"]


# ---------------------------------------------------------------------------
# M5 Phase A.0 Task 0a: voice red-line — only author_role='ingest' may write
# page_type='voice' (Codex round 1 Finding 1)
# ---------------------------------------------------------------------------


def test_voice_write_from_query_author_role_rejected(tmp_path: Path) -> None:
    """Codex round 1 Finding 1: only author_role='ingest' may write page_type='voice'.
    The empty-sources fast-path of _enforce_voice_red_line previously allowed
    arbitrary callers to corrupt voice.md."""
    vault = _vault(tmp_path)
    with pytest.raises(ValueError, match="page_type='voice'"):
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=[], confidence="low",
            body="# 总体基调\n伪造\n", author_role="query",
        )


def test_voice_write_from_user_author_role_rejected(tmp_path: Path) -> None:
    """Same guard for author_role='user' (Phase C review path)."""
    vault = _vault(tmp_path)
    with pytest.raises(ValueError, match="page_type='voice'"):
        merge_note.write(
            vault_dir=vault, page_type="voice", title=None,
            sources=[], confidence="low",
            body="# x\n", author_role="user",
        )


def test_voice_write_from_ingest_still_allowed(tmp_path: Path) -> None:
    """Sanity: the guard does NOT break legitimate ingest voice writes."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="voice", title=None,
        sources=[], confidence="low",
        body="# 总体基调\n初始化\n", author_role="ingest",
    )
    assert (vault / "wiki" / "voice.md").is_file()


# ---------------------------------------------------------------------------
# M5 Phase A.0 Task 0b: byte-equal idempotency — same body+sources+confidence+
# needs_review = no-op (Codex round 1 Finding 6 + round 3 Finding A)
# ---------------------------------------------------------------------------


def test_write_byte_equal_body_and_sources_is_idempotent_no_conflict(tmp_path: Path) -> None:
    """Codex round 1 Finding 6: re-writing a synthesis with the same body
    and sources must be a no-op — no CONFLICT marker, no needs_review flip."""
    vault = _vault(tmp_path)
    body = "# RAG 立场综述\n\n## 综述\n本质上,ta 倾向 lite-RAG\n"
    merge_note.write(
        vault_dir=vault, page_type="synthesis", title="RAG 立场综述",
        sources=["src-1", "src-7"], confidence="medium",
        body=body, author_role="query",
    )
    page = vault / "wiki" / "syntheses" / "RAG 立场综述.md"
    text_first = page.read_text(encoding="utf-8")
    fm_first = yaml.safe_load(text_first.split("---")[1])
    last_modified_first = fm_first["last_modified"]
    # Second write — byte-equal body + sources
    merge_note.write(
        vault_dir=vault, page_type="synthesis", title="RAG 立场综述",
        sources=["src-1", "src-7"], confidence="medium",
        body=body, author_role="query",
    )
    text_second = page.read_text(encoding="utf-8")
    fm_second = yaml.safe_load(text_second.split("---")[1])
    # No CONFLICT marker
    assert "⚠️ CONFLICT" not in text_second
    # No needs_review flip
    assert fm_second["needs_review"] is False
    # last_modified unchanged → idempotent (page bytes identical OR fm.last_modified preserved)
    assert text_first == text_second or fm_second["last_modified"] == last_modified_first


def test_write_byte_equal_body_but_confidence_change_still_writes(tmp_path: Path) -> None:
    """Codex round 3 Finding A: idempotency guard must NOT short-circuit when
    confidence is being promoted, even if body and sources are byte-equal.
    Otherwise apply_review_accept-via-write semantics break silently."""
    vault = _vault(tmp_path)
    body = "# X\n\n## 概述\nv1\n"
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="low",
        body=body, author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="high",  # promoted
        body=body, author_role="ingest",
    )
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["confidence"] == "high", (
        "confidence promotion must persist — idempotency only short-circuits "
        "when body+sources+confidence+needs_review all match"
    )


def test_write_byte_equal_but_needs_review_clear_still_writes(tmp_path: Path) -> None:
    """Codex round 3 Finding A: same for needs_review clearing."""
    vault = _vault(tmp_path)
    body = "# X\n\n## 概述\nv1\n"
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="medium", needs_review=True,
        body=body, author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="medium", needs_review=False,
        body=body, author_role="ingest",
    )
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["needs_review"] is False


def test_write_different_body_same_section_still_conflicts(tmp_path: Path) -> None:
    """Sanity: idempotency only triggers on byte-equal. Different body
    in same H2 still emits CONFLICT marker as before (M3 behavior preserved)."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-1"], confidence="medium",
        body="# X\n\n## 概述\nv1\n", author_role="ingest",
    )
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-2"], confidence="medium",
        body="# X\n\n## 概述\nv2\n", author_role="ingest",
    )
    text = (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8")
    assert "⚠️ CONFLICT" in text


# ---------------------------------------------------------------------------
# M5 Phase A.0 Task 0c: voice_md_is_valid — frontmatter-parsing voice.md
# sanity check (Codex round 1 Finding 5)
# ---------------------------------------------------------------------------


def test_voice_md_valid_returns_true_for_well_formed(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "wiki" / "voice.md").write_text(
        "---\npage_type: voice\nsources: [src-1]\nconfidence: medium\n---\n\n# x\n",
        encoding="utf-8",
    )
    assert merge_note.voice_md_is_valid(vault) is True


def test_voice_md_valid_returns_false_for_missing(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # no voice.md
    assert merge_note.voice_md_is_valid(vault) is False


def test_voice_md_valid_returns_false_for_empty_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "wiki" / "voice.md").write_text("", encoding="utf-8")
    assert merge_note.voice_md_is_valid(vault) is False


def test_voice_md_valid_returns_false_for_malformed_yaml(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "wiki" / "voice.md").write_text(
        "---\nthis is not: valid: yaml: at all: [\n---\n# x\n",
        encoding="utf-8",
    )
    assert merge_note.voice_md_is_valid(vault) is False


def test_voice_md_valid_returns_false_for_wrong_page_type(tmp_path: Path) -> None:
    """Defensive: a file that parses but says page_type: persona is not a voice page."""
    vault = _vault(tmp_path)
    (vault / "wiki" / "voice.md").write_text(
        "---\npage_type: persona\nsources: [src-1]\nconfidence: medium\n---\n\n# x\n",
        encoding="utf-8",
    )
    assert merge_note.voice_md_is_valid(vault) is False


# ---------------------------------------------------------------------------
# M5 Phase A.0 Task 0d: _validate_title length / whitespace / reserved-name
# hardening (Codex round 3 Finding D)
# ---------------------------------------------------------------------------


def test_validate_title_rejects_whitespace_only(tmp_path: Path) -> None:
    """Codex round 3 Finding D: trim-then-empty titles must be rejected."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.TitleUnsafeError):
        merge_note.write(
            vault_dir=vault, page_type="entity", title="   ",
            sources=["src-1"], confidence="medium",
            body="# x\n", author_role="ingest",
        )


def test_validate_title_rejects_too_long(tmp_path: Path) -> None:
    """Codex round 3 Finding D: 201+ char titles overflow filesystem paths
    on some setups. Cap at 200."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.TitleUnsafeError):
        merge_note.write(
            vault_dir=vault, page_type="entity", title="x" * 201,
            sources=["src-1"], confidence="medium",
            body="# x\n", author_role="ingest",
        )


@pytest.mark.parametrize("reserved", ["index", "index.md", ".gitkeep"])
def test_validate_title_rejects_reserved_names(tmp_path: Path, reserved: str) -> None:
    """Codex round 3 Finding D: reserved internal names cannot be used as
    page titles — they shadow vault internals."""
    vault = _vault(tmp_path)
    with pytest.raises(merge_note.TitleUnsafeError):
        merge_note.write(
            vault_dir=vault, page_type="entity", title=reserved,
            sources=["src-1"], confidence="medium",
            body="# x\n", author_role="ingest",
        )


def test_validate_title_accepts_normal_titles(tmp_path: Path) -> None:
    """Sanity: the new checks don't false-positive on legitimate titles."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="XX 项目",
        sources=["src-1"], confidence="medium",
        body="# x\n", author_role="ingest",
    )
    assert (vault / "wiki" / "entities" / "XX 项目.md").is_file()


# ---------------------------------------------------------------------------
# M6 Task 0c — forget_rewrite (Codex round 1 Findings 2+3+7, round 2 Finding F)
# ---------------------------------------------------------------------------


def test_forget_rewrite_replaces_sources_not_union(tmp_path: Path) -> None:
    """Codex round 1 Finding 3: forget Level 2 must remove src from sources,
    not merge into existing list."""
    vault = _vault(tmp_path)
    merge_note.write(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0013", "src-0014"], confidence="high",
        body="# X\n## 概述\nv1\n", author_role="ingest",
    )
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0014"],   # explicitly excludes src-0013
        confidence="medium", needs_review=True,
        body="# X\n## 概述\n仅 src-0014 支撑\n",
    )
    fm = yaml.safe_load(
        (vault / "wiki" / "entities" / "X.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["sources"] == ["src-0014"]
    assert "src-0013" not in fm["sources"]
    assert fm["last_modified_by"] == "user"


def test_forget_rewrite_clears_forget_dirty_marker(tmp_path: Path) -> None:
    """forget_dirty marker (placed by forget_level2_start) must be removed
    after rewrite — its presence signals 'pending forget rewrite'."""
    vault = _vault(tmp_path)
    page = vault / "wiki" / "entities" / "X.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\npage_type: entity\ntitle: X\nsources: [src-0013, src-0014]\n"
        "confidence: medium\nneeds_review: true\npinned_fields: []\n"
        "forget_dirty: src-0013\n"
        "last_modified: 2026-04-30T10:00:00+08:00\n"
        "last_modified_by: ingest\n---\n\n# X\n## 概述\n旧\n",
        encoding="utf-8",
    )
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0014"], confidence="low", needs_review=True,
        body="# X\n## 概述\n新\n",
    )
    fm = yaml.safe_load(page.read_text(encoding="utf-8").split("---")[1])
    assert "forget_dirty" not in fm


def test_forget_rewrite_preserves_allowed_extra_frontmatter(tmp_path: Path) -> None:
    """Codex round 2 Finding F: M3 allow-listed extra frontmatter (e.g.
    voice_evidence) must survive forget_rewrite, not be silently dropped."""
    vault = _vault(tmp_path)
    page = vault / "wiki" / "entities" / "X.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    # Write with a key allowed by M3's _ALLOWED_EXTRA_FRONTMATTER (check the
    # actual M3 module — for this test use whatever key the M3 allow-list
    # actually permits. Skip if the allow-list has no test-friendly key.)
    import clonemate.merge_note as mn
    if not mn._ALLOWED_EXTRA_FRONTMATTER:
        pytest.skip("M3 allow-list is empty; nothing to preserve")
    test_key = next(iter(mn._ALLOWED_EXTRA_FRONTMATTER))
    expected_type = mn._ALLOWED_EXTRA_FRONTMATTER[test_key]
    # Generate a minimal valid value for the type
    if expected_type is list:
        test_value = ["test"]
    elif expected_type is dict:
        test_value = {"k": "v"}
    elif expected_type is str:
        test_value = "test"
    elif expected_type is int:
        test_value = 1
    else:
        pytest.skip(f"Don't know how to construct {expected_type}")
    # Plan deviation: plan used `yaml.safe_dump(test_value).strip()` which
    # for atomic types (int/str) produces a YAML document-end marker `...`
    # that breaks the surrounding frontmatter. Use inline-flow yaml dump
    # of a single-entry dict to get a proper inline literal for any type.
    inline = yaml.safe_dump({test_key: test_value}, default_flow_style=True).strip()
    # yaml.safe_dump({'few_shot_count': 1}, default_flow_style=True) →
    # '{few_shot_count: 1}\n' — strip braces to get a frontmatter-friendly line.
    if inline.startswith("{") and inline.endswith("}"):
        inline = inline[1:-1].strip()
    page.write_text(
        f"---\npage_type: entity\ntitle: X\nsources: [src-0001, src-0002]\n"
        f"confidence: medium\nneeds_review: false\npinned_fields: []\n"
        f"forget_dirty: src-0001\n"
        f"{inline}\n"
        f"last_modified: 2026-04-30T10:00:00+08:00\n"
        f"last_modified_by: ingest\n---\n\n# X\n",
        encoding="utf-8",
    )
    merge_note.forget_rewrite(
        vault_dir=vault, page_type="entity", title="X",
        sources=["src-0002"], confidence="low", needs_review=True,
        body="# X\n",
    )
    fm = yaml.safe_load(page.read_text(encoding="utf-8").split("---")[1])
    assert test_key in fm, f"forget_rewrite must preserve allow-listed extra key {test_key!r}"
    # forget_dirty cleared
    assert "forget_dirty" not in fm


def test_forget_rewrite_rejects_voice_page(tmp_path: Path) -> None:
    """Codex round 1 Finding 7: voice red line still applies — forget Level 2
    cannot mutate wiki/voice.md from author_role='user'."""
    vault = _vault(tmp_path)
    with pytest.raises(ValueError, match="voice"):
        merge_note.forget_rewrite(
            vault_dir=vault, page_type="voice", title=None,
            sources=[], confidence="low", needs_review=True,
            body="# template\n",
        )
