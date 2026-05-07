"""query_cmd — Phase ask orchestrator.

Phase ask (this module emits a prompt; Claude main conversation drives):
  4a. Fact synthesis from candidate wiki pages
  4b. Voice transfer (Read wiki/voice.md → rewrite in target's tone)
  4c. Append disclaimer (固定免责语 per spec §6.3)

This module DOES NOT call any LLM (spec §4.2). It produces a structured
prompt that Claude reads and executes.

Three modes:
  - default     : 4a + 4b + 4c (full pipeline; voice transfer ON)
  - literal     : 4a + 4c (skip voice transfer; neutral factual summary)
  - voice-only  : 4b + 4c (style fidelity > fact completeness; rare)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

_VALID_MODES = {"default", "literal", "voice-only"}


def _human_age(iso_ts: str) -> str:
    """Render a rough Chinese human-readable age string given an ISO 8601
    timestamp. Returns an empty string when the timestamp cannot be parsed
    (caller should suppress the age suffix gracefully).

    Examples: "5 分钟前", "2 小时前", "3 天前", "12 天前".
    """
    if not iso_ts or iso_ts == "unknown":
        return ""
    try:
        # datetime.fromisoformat handles offsets in Python 3.11+
        dt = datetime.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo is not None else datetime.now()
    try:
        delta = now - dt
    except TypeError:
        # Mixed naive / aware
        return ""
    secs = int(delta.total_seconds())
    if secs < 0:
        # Future timestamp — treat as just-now
        return "刚刚"
    if secs < 60:
        return f"{secs} 秒前"
    if secs < 3600:
        return f"{secs // 60} 分钟前"
    if secs < 86400:
        return f"{secs // 3600} 小时前"
    return f"{secs // 86400} 天前"


def _freshness_block(last_sync_run_at: str | None) -> str:
    """Build the '## 数据新鲜度' section appended into the orchestration
    prompt. Used by all three modes."""
    if not last_sync_run_at:
        ts_display = "unknown"
        age_suffix = ""
    else:
        ts_display = str(last_sync_run_at)
        age = _human_age(ts_display)
        age_suffix = f"  (距当前请求约 {age})" if age else ""
    return (
        "## 数据新鲜度\n\n"
        f"- vault 上次完整 sync: {ts_display}{age_suffix}\n"
        "- 答案 4c disclaimer 里的“截至 YYYY-MM-DD” → "
        "**请用上一行的 `last_sync_run_at` 日期** (YYYY-MM-DD 部分),"
        "不要用今天的日历日期\n"
        "- 当前请求结束后会**自动触发后台 sync**(不阻塞此次回答),"
        "下一次 ask 时就会看到更新后的数据\n\n"
    )


def spawn_background_sync(
    vault_dir: Path,
    *,
    my_open_id: str,
    profile: str | None = None,
    extra_env: dict[str, str] | None = None,
    min_interval_seconds: int = 0,
) -> dict:
    """Fire-and-forget an incremental sync in the background. Does NOT wait.

    Returns a dict ``{"spawned": bool, "reason": str, "pid": int|None}``.

    Side effects (in ``vault_dir``):

      - ``.bg_sync.pid`` : PID file of the spawned process.
      - ``.bg_sync.log`` : merged stdout+stderr of the sync subprocess.

    Behavior:

      - If ``.bg_sync.pid`` exists and the PID is alive → skip
        ("already running").
      - If ``.bg_sync.pid`` exists but the PID is dead → reclaim
        (delete + spawn fresh).
      - If ``min_interval_seconds > 0`` and
        ``now - last_sync_run_at < min_interval_seconds`` → skip
        ("too recent").
      - Otherwise: spawn ``python -m clonemate sync ...`` detached via
        ``start_new_session=True`` so the parent can exit immediately.
    """
    vault_dir = Path(vault_dir)
    pid_file = vault_dir / ".bg_sync.pid"
    log_file = vault_dir / ".bg_sync.log"

    # Already-running check (with stale-PID reclaim)
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing_pid = None
        if existing_pid is not None:
            try:
                os.kill(existing_pid, 0)
            except OSError:
                # PID dead — reclaim
                try:
                    pid_file.unlink()
                except OSError:
                    pass
            else:
                return {
                    "spawned": False,
                    "reason": "already running",
                    "pid": existing_pid,
                }

    # Read _clone.yaml for last_sync_run_at (controls min-interval and the
    # one-shot full-sync vs --retry-failed decision).
    last_sync_iso: str | None = None
    cy_path = vault_dir / "_clone.yaml"
    if cy_path.exists():
        try:
            cy = yaml.safe_load(cy_path.read_text(encoding="utf-8")) or {}
            last_sync_iso = cy.get("last_sync_run_at")
        except (OSError, yaml.YAMLError):
            last_sync_iso = None

    if min_interval_seconds > 0 and last_sync_iso:
        try:
            last_dt = datetime.fromisoformat(str(last_sync_iso))
            now = (
                datetime.now(last_dt.tzinfo)
                if last_dt.tzinfo is not None
                else datetime.now()
            )
            elapsed = (now - last_dt).total_seconds()
            if 0 <= elapsed < min_interval_seconds:
                return {
                    "spawned": False,
                    "reason": (
                        f"too recent ({int(elapsed)}s < "
                        f"{min_interval_seconds}s)"
                    ),
                    "pid": None,
                }
        except (ValueError, TypeError):
            # Unparsable — fall through and spawn anyway.
            pass

    cmd = [
        sys.executable,
        "-m",
        "clonemate",
        "sync",
        "--root",
        str(vault_dir.parent),
        "--slug",
        vault_dir.name,
        "--my-open-id",
        my_open_id,
    ]
    # If we've never synced before, do a clean full incremental (no
    # --retry-failed); otherwise opportunistically retry past failures.
    if last_sync_iso:
        cmd.append("--retry-failed")

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    log_fh = open(log_file, "ab")
    try:
        proc = subprocess.Popen(  # noqa: S603 — explicit detached spawn
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
            cwd=str(vault_dir.parent),
        )
    finally:
        # Popen dup'd the fd; we can drop our handle.
        log_fh.close()

    try:
        pid_file.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        # PID file is best-effort; the subprocess is still running.
        pass

    return {"spawned": True, "reason": "ok", "pid": proc.pid}


def emit_prompt(
    vault_dir: Path | str,
    question: str,
    *,
    mode: str = "default",
) -> str:
    """Build the Phase ask orchestration message for Claude main conversation.

    Args:
      vault_dir: path to vault (parent of `wiki/`).
      question: the user's verbatim question.
      mode: 'default' (voice + facts + disclaimer),
            'literal' (facts + disclaimer, no voice),
            'voice-only' (voice + disclaimer; rare).

    Raises:
      ValueError: when mode is not one of _VALID_MODES.
      FileNotFoundError: when _clone.yaml or index.md is missing.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    # Codex round 1 Finding 5: voice.md must parse as valid voice frontmatter,
    # not just exist. Use merge_note.voice_md_is_valid (Task 0c) for the check.
    from clonemate import merge_note

    voice_usable = merge_note.voice_md_is_valid(vault_dir)
    if mode == "voice-only" and not voice_usable:
        raise FileNotFoundError(
            f"voice-only mode requires usable {vault_dir / 'wiki' / 'voice.md'} "
            "(present + parseable + page_type: voice); "
            "run ingest to (re)generate it, or use --literal."
        )
    needs_review = _scan_needs_review_pages(vault_dir)
    last_sync_run_at = cy.get("last_sync_run_at")
    freshness_block = _freshness_block(last_sync_run_at)
    base = _PROMPT_TEMPLATES[mode].format(
        vault_dir=vault_dir,
        root=vault_dir.parent,
        slug=cy["slug"],
        target_open_id=cy["identity"]["open_id"],
        display_name=cy["display_name"],
        question=question,
        freshness_block=freshness_block,
    )
    fallback = (
        _VOICE_MISSING_FALLBACK_BLOCK
        if (mode == "default" and not voice_usable)
        else ""
    )
    return base + fallback + _render_needs_review_warning_block(needs_review)


_VOICE_MISSING_FALLBACK_BLOCK = (
    "\n## ⚠️ voice.md 缺失 — degrade to literal\n\n"
    "本 vault 当前没有 `wiki/voice.md`(可能首次 ingest 时 voice few-shot 不足)。"
    "Default 模式自动降级为 **literal** 行为:跳过 4b voice transfer,只做 4a "
    "事实合成 + 4c 中性免责语。**不要**模仿 ta 语气。\n"
)


def _scan_needs_review_pages(vault_dir: Path) -> list[str]:
    """Return relpaths (vault-relative, forward-slash) of pages with
    `needs_review: true` in frontmatter. Used to warn the user when
    answers cite unresolved material."""
    out: list[str] = []
    wiki = vault_dir / "wiki"
    if not wiki.is_dir():
        return out
    for path in sorted(wiki.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue
        if isinstance(fm, dict) and fm.get("needs_review") is True:
            out.append(str(path.relative_to(vault_dir)).replace("\\", "/"))
    return out


def _escape_backticks(s: str) -> str:
    """Codex round 2 Finding (LOW): page paths in inline code can break
    Markdown rendering if they contain backticks. Strip them — they're never
    legal in a wiki page filename anyway, but defense-in-depth is cheap."""
    return s.replace("`", "")


def _render_needs_review_warning_block(pages: list[str]) -> str:
    if not pages:
        return ""  # no warning needed
    bullets = "\n".join(f"- `{_escape_backticks(p)}`" for p in pages)
    return (
        "\n## ⚠️ 含未复核条目 (spec §6.3 step 8)\n\n"
        "以下 wiki 页面 frontmatter `needs_review: true`,事实尚未确认。"
        "**若答案引用了这些页面**,在末尾免责语之前追加一行:\n\n"
        "  > ⚠️ 含未复核条目:本答案部分内容来自尚未与 ta 确认的页面。\n\n"
        "未复核页面列表:\n"
        f"{bullets}\n"
    )


_PROMPT_TEMPLATES: dict[str, str] = {}

_PROMPT_TEMPLATES["default"] = """\
# CloneMate ask — Phase ask orchestration (default mode)

You are Claude main conversation, invoked by `clonemate ask {slug} "<question>"`.
Vault path:

  {vault_dir}

Identity:
- target_open_id: {target_open_id}
- display_name:   {display_name}

Question (verbatim):
  {question}

{freshness_block}## What this is

Phase ask delivers a voice-transferred answer to the user. The pipeline has
three steps (spec §6.3 4a/4b/4c):

  4a. **事实合成** — read `index.md` → pick top-5 candidate wiki pages →
      read them; if a candidate is incomplete, follow `sources:` back to
      `raw/<src_type>/<src_id>.md`. Build the answer body from materials with
      raw / wiki support ONLY. **Do NOT fabricate.**
  4b. **voice transfer** — Read `wiki/voice.md`. Rewrite the synthesis from
      4a in ta's tone, sentence patterns, 口头禅, punctuation. Use ta's
      few-shots as in-context style seeds. **Must** include at least one
      high-frequency 口头禅 if the question scenario allows.
  4c. **完整性兜底** — append the disclaimer verbatim:

      > — 以上为 CloneMate 基于截至 YYYY-MM-DD 的公开材料合成,
      > 语气模仿 ta 但非 ta 本人。关键决策建议直接与 ta 确认。
      > 引用:(src-XXX, <relevant wiki page>)

      Replace `YYYY-MM-DD` with the date portion of `last_sync_run_at` shown
      in 数据新鲜度 above (data freshness, not today's calendar date), and
      list the actual src_ids / wiki pages you used.

## Red lines (spec §8.5)

- **事实不漂移**: voice transfer 只许重写措辞,不许添加 ta 没说过的观点。
  无 source 支撑的句子要软化为"基于现有材料无法判断"。
- **作者归属红线**: 答案中引用的句子必须来自 `author_open_id == {target_open_id}`
  的 raw / wiki 内容;严禁把他人言论(群聊上下文 / 他人评论)归到 ta。
- **免责语必带**: 4c 的 disclaimer 不可省略,即使答案很短。
- voice 内容只读不写;Phase ask 绝不修改 `wiki/voice.md`。

## Synthesis writeback (optional)

If your answer is **a cross-page synthesis** (compares ≥2 wiki pages, gives
a new comparison, or makes an explicit stance the wiki didn't yet record),
crystallize it as a synthesis page:

```python
from clonemate import merge_note
merge_note.write(
    vault_dir=Path("{vault_dir}"),
    page_type="synthesis",
    title="<a stable, kebab-acceptable Chinese/英文 title>",
    sources=[<src_ids you used>],
    confidence="medium",
    body="<the answer body without disclaimer; H2-organized>",
    author_role="query",
)
```

If your answer is just retrieval / a single-page direct quote, do NOT write a
synthesis. Default is "skip writeback."

## Finish

After answering the user (and optionally writing a synthesis), run:

  python -m clonemate ask-finish \\
    --root {root} --slug {slug} \\
    --question "<verbatim question>" \\
    --synthesis-written {{0|1}} \\
    [--synthesis-title "<title used above>"]

The finish command appends the log, rebuilds the index iff a synthesis was
written, and auto-commits the vault. Stop after finish — do not proceed to
lint (M6) or feed (M7).

See `references/prompt-query.md` for the per-step rubric and
`references/workflow-query.md` for the trigger / writeback / exit contract.
"""

_PROMPT_TEMPLATES["literal"] = """\
# CloneMate ask — Phase ask orchestration (literal mode)

You are Claude main conversation, invoked by `clonemate ask {slug} "<question>" --literal`.
Vault path:

  {vault_dir}

Identity:
- target_open_id: {target_open_id}
- display_name:   {display_name}

Question (verbatim):
  {question}

{freshness_block}## What this is

`--literal` mode: facts only, neutral tone. **Do not read voice.md** (i.e.
`wiki/voice.md`). **Do not** voice-transfer. Output a sober factual summary
the user can quote or cite without it sounding like ta.

Pipeline (spec §6.3 4a + 4c only — skip 4b):

  4a. **事实合成** — read `index.md` → pick candidate wiki pages → assemble
      a neutral, factual summary. Cite src_ids inline.
  4b. **(skipped — no voice transfer in literal mode)**
  4c. **完整性兜底** — append the literal-mode disclaimer:

      > — 以上为 CloneMate 基于截至 YYYY-MM-DD 的公开材料生成的中性事实归纳,
      > 不模仿 ta 语气。关键决策建议直接与 ta 确认。
      > 引用:(src-XXX, <relevant wiki page>)

      Replace `YYYY-MM-DD` with the date portion of `last_sync_run_at` shown
      in 数据新鲜度 above (data freshness, not today's calendar date).

## Red lines (spec §8.5)

- **事实不漂移**: 无 source 支撑的句子软化为"基于现有材料无法判断"。
- **作者归属红线**: 引用的句子必须来自 `author_open_id == {target_open_id}`
  的 raw / wiki;严禁把他人言论归到 ta。
- **免责语必带**: 4c 的 literal-mode disclaimer 不可省略。
- 不读、不引用 `wiki/voice.md`。

## Synthesis writeback (optional)

Same rules as default mode — only crystallize if the answer is a true
cross-page synthesis. Use `merge_note.write(page_type='synthesis',
author_role='query', ...)`.

## Finish

  python -m clonemate ask-finish \\
    --root {root} --slug {slug} \\
    --question "<verbatim question>" \\
    --synthesis-written {{0|1}} \\
    [--synthesis-title "<title>"]

See `references/prompt-query.md` for the literal-mode rubric.
"""

_PROMPT_TEMPLATES["voice-only"] = """\
# CloneMate ask — Phase ask orchestration (voice-only mode)

You are Claude main conversation, invoked by `clonemate ask {slug} "<question>" --voice-only`.
Vault path:

  {vault_dir}

Identity:
- target_open_id: {target_open_id}
- display_name:   {display_name}

Question (verbatim):
  {question}

{freshness_block}## What this is

`--voice-only` 模式罕用。事实完整性可降级,**风格保真度优先**。典型用例:
用户想看一段 ta 风格的轻量回应(社交场景、问候、表态),不需要严格事实合成。

Pipeline:

  4a. **事实最小化合成** — 仅取 1-2 个最相关的 wiki / raw 句子(可省略
      详细引用),但仍需 `author_open_id == {target_open_id}` 来源。
  4b. **voice transfer(全功率)** — Read `wiki/voice.md`。**风格优先**:
      口头禅、句式、标点必须高匹配;若 question 触发场景分段(§1v1 / §群聊
      / §文档评审),按场景模仿对应段的 few-shot。
  4c. **完整性兜底** — 同 default mode disclaimer:

      > — 以上为 CloneMate 基于截至 YYYY-MM-DD 的公开材料合成,
      > 语气模仿 ta 但非 ta 本人。关键决策建议直接与 ta 确认。
      > 引用:(src-XXX)

      Replace `YYYY-MM-DD` with the date portion of `last_sync_run_at` shown
      in 数据新鲜度 above (data freshness, not today's calendar date).

## Red lines (spec §8.5)

- **事实不漂移依然适用** — 风格保真不等于编造。无 source 支撑的事实陈述
  禁止生成,即使语气很像 ta。
- **作者归属红线**: 仅模仿 `author_open_id == {target_open_id}` 的素材。
- **免责语必带**。

## Synthesis writeback

Voice-only 模式产出**几乎不**写 synthesis(没有真正"跨页综合")。除非
答案确实跨多页,默认 `--synthesis-written 0`。

## Finish

  python -m clonemate ask-finish \\
    --root {root} --slug {slug} \\
    --question "<verbatim question>" \\
    --synthesis-written {{0|1}}

See `references/prompt-query.md`.
"""


def finish(
    vault_dir: Path | str,
    *,
    question: str,
    synthesis_written: bool,
    synthesis_title: str | None = None,
) -> None:
    """Called after Claude main conversation finishes Phase ask.

    - log_append: `query: "<question>" → +0|1 synthesis`
    - if synthesis_written: index_upsert.rebuild
    - git_ops._auto_commit_vault (idempotent — Codex round 4 Finding 11)

    Raises:
      ValueError: if synthesis_written=True but synthesis_title is empty.
    """
    if synthesis_written and not synthesis_title:
        raise ValueError(
            "synthesis_title is required when synthesis_written=True"
        )
    vault_dir = Path(vault_dir)
    cy = yaml.safe_load((vault_dir / "_clone.yaml").read_text(encoding="utf-8"))
    log = vault_dir / "log.md"
    # lazy import to break cycles
    from clonemate import git_ops, index_upsert, log_append

    if synthesis_written:
        index_upsert.rebuild(
            vault_dir, display_name=cy["display_name"], log_path=log,
        )

    log_append.append(
        log, op="query", subject=_sanitize_question_for_log(question),
        metric=f"+{1 if synthesis_written else 0} synthesis"
        + (f" — {synthesis_title}" if synthesis_written and synthesis_title else ""),
    )
    git_ops._auto_commit_vault(
        vault_dir,
        message=f"query: +{1 if synthesis_written else 0} synthesis"
        + (f" — {synthesis_title}" if synthesis_written and synthesis_title else ""),
    )


_NEWLINE_RE = re.compile(r"\s+", re.MULTILINE)
# Codex round 2 Finding (LOW): strip ANSI escapes + control / format characters
# before logging so a crafted question can't break terminal output or hide
# bytes in log.md. Covers CSI sequences, C0 + DEL controls, and Cf-class
# bidi/format characters (U+200B-U+200F, U+202A-U+202E, U+2060-U+206F).
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
    r"​-‏‪-‮⁠-⁯]"
)


def _sanitize_question_for_log(question: str) -> str:
    """Strip ANSI + control chars, collapse whitespace, truncate."""
    stripped = _ANSI_RE.sub("", question)
    stripped = _CONTROL_RE.sub("", stripped)
    flat = _NEWLINE_RE.sub(" ", stripped.strip())
    if len(flat) > 200:
        flat = flat[:197] + "..."
    return f"\"{flat}\""
