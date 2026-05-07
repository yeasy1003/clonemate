"""Python plumbing e2e for M4 review — runs in CI (no real LLM)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml
from clonemate import merge_note, review_cmd

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "vaults" / "m4-fixture"


def _copy(tmp_path: Path) -> Path:
    vault = tmp_path / "zhangsan"
    shutil.copytree(_FIXTURE, vault)
    return vault


def _git_init(vault: Path) -> None:
    """Initialize a git repo in the vault so `_auto_commit_vault` can land.

    The fixture isn't a git repo by default; review_cmd.finish + ingest_cmd.finish
    auto-commit the vault (Codex round 3 Finding 9), so any test that exercises
    `finish` must seed a real git repo first.
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


def test_build_checklist_finds_all_4_buckets(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    cl = review_cmd.build_checklist(vault)
    assert cl.total_items() >= 4
    assert any(c.section_name == "概述" for c in cl.conflicts)
    assert any(p.title == "张三" for p in cl.needs_review_pages)
    assert cl.ambiguities and "X-service" in cl.ambiguities[0].description
    assert cl.unclear_topics and "RAG" in cl.unclear_topics[0].topic


def test_emit_prompt_renders_checklist(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    prompt = review_cmd.emit_prompt(vault)
    assert "Conflicts" in prompt
    assert "Needs review" in prompt
    assert "Ambiguities" in prompt
    assert "Unclear" in prompt
    assert "wiki/persona.md" in prompt
    assert "wiki/entities/XX 项目.md" in prompt


def test_phase_c_apply_review_accept_persona(tmp_path: Path) -> None:
    """User accepts the low-confidence persona; needs_review flips to false."""
    vault = _copy(tmp_path)
    merge_note.apply_review_accept(
        vault_dir=vault, page_type="persona", title=None,
        confidence="high", pin_fields=["职责", "沟通偏好"],
    )
    fm = yaml.safe_load((vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1])
    assert fm["needs_review"] is False
    assert fm["confidence"] == "high"
    assert "职责" in fm["pinned_fields"]
    assert "沟通偏好" in fm["pinned_fields"]


def test_phase_c_resolve_conflict_drops_marker(tmp_path: Path) -> None:
    """User resolves the conflict by accepting v2; marker drops."""
    vault = _copy(tmp_path)
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="XX 项目",
        section_name="概述",
        accepted_body="v2 版本(用户确认保留)\n",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "entities" / "XX 项目.md").read_text(encoding="utf-8")
    assert "⚠️ CONFLICT" not in text
    assert "v2 版本(用户确认保留)" in text
    # Disjoint section still present (along with its AMBIGUOUS marker, which is
    # a separate item the user must process)
    assert "## 协作画像" in text
    assert "⚠️ AMBIGUOUS" in text


def test_finish_appends_log_with_counts(tmp_path: Path) -> None:
    vault = _copy(tmp_path)
    # Plan correction: review_cmd.finish auto-commits (Codex round 3 Finding 9),
    # so the fixture needs to be a real git repo.
    _git_init(vault)
    review_cmd.finish(vault, resolved=3, skipped=1)
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "review" in log
    assert "+3 resolved / +1 skipped" in log


def test_phase_c_skip_keeps_item_for_next_round(tmp_path: Path) -> None:
    """Skipped items remain — next checklist still surfaces them."""
    vault = _copy(tmp_path)
    cl1 = review_cmd.build_checklist(vault)
    assert cl1.conflicts  # initial fixture has the CONFLICT marker
    # User resolves only the conflict; everything else skipped.
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="entity", title="XX 项目",
        section_name="概述", accepted_body="resolved\n",
        decided_by_user=True,
    )
    cl2 = review_cmd.build_checklist(vault)
    # Conflict gone, but needs_review + ambiguity + unclear still there.
    # NB: XX 项目 still carries an AMBIGUOUS marker, so _recompute_needs_review
    # flips its frontmatter to needs_review=true — Phase B re-surfaces it as a
    # needs_review item. The user-visible invariant the test cares about is that
    # the conflict bucket is now empty and the other buckets are still pending.
    assert not cl2.conflicts
    assert cl2.needs_review_pages
    assert cl2.ambiguities
    assert cl2.unclear_topics


def test_empty_vault_emit_prompt_says_no_items(tmp_path: Path) -> None:
    """When wiki is clean, prompt tells the user explicitly."""
    vault = tmp_path / "zhangsan"
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "syntheses").mkdir(parents=True)
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "_clone.yaml").write_text(yaml.safe_dump({
        "slug": "zhangsan", "identity": {"open_id": "ou_xxxxxxxxxxxxxxxx",
        "app_id": "cli_xxxxxxxxxxxxxxxx"}, "display_name": "张三",
        "profile": "claude-code",
    }, allow_unicode=True), encoding="utf-8")
    prompt = review_cmd.emit_prompt(vault)
    assert "no items" in prompt.lower() or "无需复核" in prompt


def test_phase_c_resolve_ambiguity_drops_marker_e2e(tmp_path: Path) -> None:
    """Codex Finding 1 e2e: user clarifies an AMBIGUOUS marker; build_checklist
    no longer surfaces it on the next pass."""
    vault = _copy(tmp_path)
    cl_before = review_cmd.build_checklist(vault)
    assert any("X-service" in a.description for a in cl_before.ambiguities)

    merge_note.resolve_ambiguity(
        vault_dir=vault, page_type="entity", title="XX 项目",
        marker_text_substring="X-service",
        replacement="它指代码库中的 X-service",
        decided_by_user=True,
    )

    cl_after = review_cmd.build_checklist(vault)
    assert not any("X-service" in a.description for a in cl_after.ambiguities)
    # Conflict in the same page is unrelated and stays
    assert cl_after.conflicts


def test_phase_c_resolve_unclear_drops_marker_e2e(tmp_path: Path) -> None:
    """Codex Finding 1 e2e: same for UNCLEAR markers."""
    vault = _copy(tmp_path)
    cl_before = review_cmd.build_checklist(vault)
    assert any("RAG" in u.topic for u in cl_before.unclear_topics)

    merge_note.resolve_unclear(
        vault_dir=vault, page_type="concept", title="RAG 立场",
        marker_text_substring="立场未明",
        replacement="ta 倾向先做最简版本",
        decided_by_user=True,
    )

    cl_after = review_cmd.build_checklist(vault)
    assert not cl_after.unclear_topics


def test_phase_c_full_loop_closes_all_4_buckets_e2e(tmp_path: Path) -> None:
    """Codex Finding 4 closing-loop e2e: process every bucket of the m4 fixture
    using the documented helper for that bucket; final build_checklist is empty."""
    vault = _copy(tmp_path)
    cl_before = review_cmd.build_checklist(vault)
    assert cl_before.total_items() >= 4

    # 1. Conflicts → resolve_conflict
    for c in cl_before.conflicts:
        merge_note.resolve_conflict(
            vault_dir=vault,
            page_type="entity",
            title=Path(c.page_relpath).stem,
            section_name=c.section_name,
            accepted_body="resolved by user",   # NB: no trailing \n; tests Finding 2
            decided_by_user=True,
        )

    # 2. needs_review pages → apply_review_accept (promote confidence)
    for p in cl_before.needs_review_pages:
        page_type = Path(p.page_relpath).parent.name.rstrip("s")
        if p.page_relpath.endswith("persona.md"):
            page_type, title = "persona", None
        elif p.page_relpath.endswith("voice.md"):
            page_type, title = "voice", None
        else:
            title = Path(p.page_relpath).stem
        merge_note.apply_review_accept(
            vault_dir=vault, page_type=page_type, title=title,
            confidence="high",
        )

    # 3. Ambiguities → resolve_ambiguity (replacement = clarification)
    for a in cl_before.ambiguities:
        page_type = "entity" if "/entities/" in a.page_relpath else "concept"
        merge_note.resolve_ambiguity(
            vault_dir=vault, page_type=page_type,
            title=Path(a.page_relpath).stem,
            marker_text_substring=a.description[:20],
            replacement=f"用户裁决:{a.description[:30]}",
            decided_by_user=True,
        )

    # 4. Unclear topics → resolve_unclear + apply_review_accept (low-conf needs explicit close)
    for u in cl_before.unclear_topics:
        page_type = "concept" if "/concepts/" in u.page_relpath else "entity"
        title = Path(u.page_relpath).stem
        merge_note.resolve_unclear(
            vault_dir=vault, page_type=page_type, title=title,
            marker_text_substring=u.topic[:15],
            replacement=f"用户补充:{u.topic[:30]}",
            decided_by_user=True,
        )
        # low-confidence concept page: also accept to clear needs_review
        merge_note.apply_review_accept(
            vault_dir=vault, page_type=page_type, title=title,
            confidence="medium",
        )

    cl_after = review_cmd.build_checklist(vault)
    assert cl_after.is_empty(), (
        f"Expected empty checklist after full Phase C loop, got "
        f"{cl_after.total_items()} items: "
        f"conflicts={cl_after.conflicts} "
        f"needs_review={cl_after.needs_review_pages} "
        f"ambiguities={cl_after.ambiguities} "
        f"unclear={cl_after.unclear_topics}"
    )


def test_phase_c_cli_handoff_round_trip_e2e(tmp_path: Path) -> None:
    """Codex Finding 4 — verify the CLI review → review-finish glue actually
    runs together. emit_prompt via `review`,then `review-finish` writes log."""
    from clonemate import __main__ as main_entry
    vault = _copy(tmp_path)
    # Plan correction: review-finish auto-commits (Codex round 3 Finding 9),
    # so the fixture needs to be a real git repo.
    _git_init(vault)
    rc = main_entry.main(["review", "--root", str(tmp_path), "--slug", "zhangsan"])
    assert rc == 0
    rc = main_entry.main([
        "review-finish",
        "--root", str(tmp_path), "--slug", "zhangsan",
        "--resolved", "0", "--skipped", "4",
    ])
    assert rc == 0
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "review" in log and "+0 resolved / +4 skipped" in log


def test_phase_c_b_path_recovers_v1_via_git_show_e2e(tmp_path: Path) -> None:
    """Codex round 3 Finding 9: after the planned ingest-finish auto-commit,
    `git show HEAD~1:<path>` must successfully recover an older section body
    so Phase C [B] (用 v1) is implementable.

    Sequence: write v1 → ingest-finish (auto-commit v1) → write v2 (creates
    CONFLICT marker referencing v1) → review starts → Claude fetches v1 from
    git → user picks [B] → resolve_conflict applies v1 body.
    """
    from clonemate import ingest_cmd, merge_note
    vault = _copy(tmp_path)
    # Init real git so commits land
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "add", "."], cwd=vault, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"], cwd=vault, check=True,
    )

    # Write v1 (clean entity, no conflict yet) and finish (auto-commit).
    merge_note.write(
        vault_dir=vault, page_type="entity", title="清洁项目",
        sources=["src-A"], confidence="medium",
        body="# 清洁项目\n\n## 概述\nv1 原始描述\n",
        author_role="ingest",
    )
    ingest_cmd.finish(vault, raw_count=1, wiki_count=1)

    # Write v2 — same H2 → CONFLICT marker injected by M3 _merge_body.
    merge_note.write(
        vault_dir=vault, page_type="entity", title="清洁项目",
        sources=["src-B"], confidence="medium",
        body="# 清洁项目\n\n## 概述\nv2 重写描述\n",
        author_role="ingest",
    )
    text_v2 = (vault / "wiki" / "entities" / "清洁项目.md").read_text(encoding="utf-8")
    assert "⚠️ CONFLICT" in text_v2 and "v2 重写描述" in text_v2

    # Phase C [B]: recover v1 via git
    show_out = subprocess.run(
        ["git", "show", "HEAD:wiki/entities/清洁项目.md"],
        cwd=vault, capture_output=True, text=True, check=True,
    ).stdout
    assert "v1 原始描述" in show_out, "git history must contain v1 body for [B] path"


def test_phase_c_b_path_uses_resolve_conflict_no_new_marker_e2e(tmp_path: Path) -> None:
    """Codex round 2 Finding 8: [B] needs_review edit path must use
    resolve_conflict (overwrite section), NOT merge_note.write (which would
    inject a new CONFLICT marker on H2 collision)."""
    vault = _copy(tmp_path)
    # User chose [B] for the persona's 职责 section: improve the wording
    merge_note.resolve_conflict(
        vault_dir=vault, page_type="persona", title=None,
        section_name="职责",
        accepted_body="后端 + AI infra(用户改写)\n",
        decided_by_user=True,
    )
    text = (vault / "wiki" / "persona.md").read_text(encoding="utf-8")
    # New body present, NO new CONFLICT marker introduced
    assert "用户改写" in text
    assert "⚠️ CONFLICT" not in text
    # Caller still needs to apply_review_accept to close the page
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["needs_review"] is True   # not yet closed
    merge_note.apply_review_accept(
        vault_dir=vault, page_type="persona", title=None,
        confidence="high", pin_fields=["职责"],
    )
    fm2 = yaml.safe_load((vault / "wiki" / "persona.md").read_text(encoding="utf-8").split("---")[1])
    assert fm2["needs_review"] is False
    assert "职责" in fm2["pinned_fields"]
