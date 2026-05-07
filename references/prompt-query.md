# Phase ask — Query Dialogue Rubric

> **Audience:** Claude main conversation, invoked by `clonemate ask <slug>
> "<question>" [--literal | --voice-only]`.

The orchestration message from `query_cmd.emit_prompt` already lists the
question, identity, mode, and any `needs_review` warnings. This document is
the per-step rubric.

## Pipeline

### 4a. 事实合成

1. Read `index.md` (cheap — full file is small per spec assumption).
2. Pick **top-5** candidate wiki pages relevant to the question. Use both
   keyword and semantic association.
3. Read the candidates. If a candidate is incomplete or referenced an
   absent fact, follow the candidate's frontmatter `sources:` list and read
   the corresponding `raw/<src_type>/<src_id>.md` to recover the original.
4. Build the answer from materials with **explicit raw / wiki support**.
   No fabrication. If a question can't be answered from the vault, say so:

   > 基于现有材料无法判断 — 请直接与 ta 确认。

### 4b. voice transfer (default & voice-only modes)

1. Read `wiki/voice.md`. Note 总体基调 / 句式特征 / 高频口头禅 / 不会出现
   的表达 / 场景分段 few-shot.
2. Match the question's scenario (1v1 / 群聊 / 文档评审) and pick the
   matching `§<scenario>` few-shots as in-context style seeds.
3. Rewrite the 4a synthesis in ta's tone. **Must** include at least one
   high-frequency 口头禅 if the scenario allows.
4. **Don't** invent facts to fill style. If a 口头禅 doesn't fit the
   scenario, omit it and pick another. Style is decoration; fact is
   substrate.

`--literal` mode: **skip 4b entirely**. Output a neutral factual summary.
`--voice-only` mode: **maximum 4b emphasis**. Style fidelity > fact
completeness. Still no fabrication.

### 4c. 完整性兜底 — disclaimer

Append the appropriate disclaimer **verbatim** before the answer ends.
Replace `YYYY-MM-DD` with today's date and `(src-XXX)` with actual src_ids.

| Mode | Disclaimer |
|---|---|
| default | `> — 以上为 CloneMate 基于截至 YYYY-MM-DD 的公开材料合成,语气模仿 ta 但非 ta 本人。关键决策建议直接与 ta 确认。引用:(src-XXX)` |
| literal | `> — 以上为 CloneMate 基于截至 YYYY-MM-DD 的公开材料生成的中性事实归纳,不模仿 ta 语气。关键决策建议直接与 ta 确认。引用:(src-XXX)` |
| voice-only | (same as default) |

### 4d. 时间引用红线

为避免 voice transfer 阶段把 wiki 里宽泛的时间提示套用到具体子问题、产生事实漂移,这一节专门约束**答案中的时间词**。

1. 答案中的**每一个时间词**(如"去年底" / "上个月" / "Q1 起" / "最近两周" / "从 X 月开始")必须可追溯到某条**具体 src** 的 `created_at` / `modified_at` / chat-month / `start_time`,且该 src 必须在你这次答案的 4a 引用列表里。
2. **禁止借用** wiki 概念页(尤其 confidence=medium / low 的 concept 页)里宽泛的时间提示(例如某 wiki 写"2025-Q4 ~ 2026-Q1 个人重点方向"),把它套用到具体子问题。那是 ingest 阶段在更大 source 集上做的聚合推断,不是当前问题范围内的具体证据。
3. 时间范围只能 "stretch as wide as your cited src timestamps actually support"。如果引用的 src 最早 2026-04-09、最晚 2026-04-27,你能说"4 月这一波集中产出"或"4 月初 ~ 4 月底",**不能**说"从去年底"或"过去半年"。
4. 当问题涉及"何时开始 / 何时结束"但 src 时间戳不足以支撑结论时,**软化措辞**:`"至少从 X 月起有动作,更早的不在我手头数据里"` / `"基于现有材料无法判断起始时间"`。

**操作流程**:在 4b voice transfer 之前,把 4a 引用的所有 src 跑一遍 grep 拿到时间戳,在心里 / 输出里固定 `earliest=YYYY-MM-DD, latest=YYYY-MM-DD` 这个范围;答案里的时间词只能落在 `[earliest, latest]` 区间内。

**短示例**:

- **bad**:`"从去年底搞到现在"`(全部 src 实际都在 2026-04 → 时间漂移)
- **good**:`"4 月这一波集中搞了一下,最早 4-9 写了验证记录,最晚 4-27 更新了 /dev-flow session"`

## Synthesis writeback (optional)

Crystallize the answer as a `wiki/syntheses/<title>.md` page only if **any**
of these is true:

- The answer compares ≥2 distinct wiki pages and produces a new comparison.
- The answer makes an explicit stance the wiki didn't yet record.
- The user follow-ups suggest the topic is recurring (rare in single-shot
  ask).

When in doubt, **skip writeback**. Synthesis pollution is a worse failure
than a missed crystallization (the next ask will recompute from the same
candidates anyway).

If you decide to write — replace the angle-bracket placeholders with real
values from the orchestration message (`<vault_dir>` is the path you got at
the top of the prompt; `<src_ids cited>` is the list of `src-XXXX` ids you
actually quoted; etc.). Do NOT paste the literal `"<vault_dir>"` string.

```python
from clonemate import merge_note
from pathlib import Path
merge_note.write(
    vault_dir=Path("<vault_dir>"),               # ← substitute real path
    page_type="synthesis",
    title="<stable kebab/Chinese title>",        # ← substitute real title
    sources=[<src_ids cited>],                   # ← substitute real list
    confidence="medium",
    body="<the answer body without the disclaimer>",  # ← substitute body
    author_role="query",
)
```

Then call `ask-finish` with `--synthesis-written 1 --synthesis-title "..."`.

## Red lines (spec §8.5)

- **事实不漂移**: voice transfer 只许重写措辞;不许添加 ta 没说过的观点。
- **作者归属红线**: 仅引用 `author_open_id == target.open_id` 的素材。
  群聊上下文中他人消息 / 他人在 ta 文档下的评论 **严禁**进入答案。
- **免责语必带**: 缺免责语 = 答案不合格。
- voice 内容**只读**;Phase ask 永不写 `wiki/voice.md`。

## ⚠️ 含未复核条目

If you cited a `wiki/.../<page>.md` whose frontmatter has `needs_review:
true`, append (above the disclaimer):

> ⚠️ 含未复核条目:本答案部分内容来自尚未与 ta 确认的页面。

Use the orchestration message's "未复核页面列表" to recognize these pages.

## Finish

```bash
python -m clonemate ask-finish \
  --root <root> --slug <slug> \
  --question "<verbatim question>" \
  --synthesis-written {0|1} \
  [--synthesis-title "<title>"]
```

Stop after finish. Do not transition to lint (M6) or feed (M7).
