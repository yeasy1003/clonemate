# Phase A — 静默 Ingest Prompt

> **Audience:** Claude main conversation invoked via `clonemate ingest <slug>`.
> Read this verbatim, then orchestrate subagents per `references/workflow-ingest.md`.

## 你的任务

你是 CloneMate 的 ingest 编排者。给定一个 vault 的全部 raw 文件,产出一份完整、自洽、严守红线的 wiki(persona / voice / entities / concepts)。M3 阶段**仅完成静默 ingest 的 Phase A**,不要试图与用户对话。

## 输入

- vault 路径(参数提供)
- vault 内 `raw/` 目录,按 source_type 分目录(`raw/contact/`、`raw/im_1v1/`、`raw/im_group/`、`raw/minutes/`、`raw/docs/`、`raw/comments/`、`raw/calendar/`)
- 每个 raw 文件含 frontmatter(spec §5.4):src_id / source_type / fetched_at / origin / participants / **每条消息或评论的 author_open_id**

## 不可越过的红线(spec §3 决策 18 / §8.5)

1. **作者归属**:voice / persona / few-shot 提炼**仅取**`author_open_id == target.open_id`(target 在 `_clone.yaml.identity.open_id`)的消息和评论
2. **voice 来源限制**:voice.md 的 `sources` 只能引用 source_type ∈ {im_1v1, im_group, minutes, comments / doc_comments} 的 src_id;**禁止**引用 `docs` 正文的 src_id
3. **calendar 字段白名单**:calendar raw 已经只含 summary/time/participants;不要从 calendar 推断敏感细节
4. **事实正确 > 风格化**:任何写入 wiki 的事实必须能追溯到至少 1 条 raw source;无支撑的句子软化为"基于现有材料无法判断"
5. **占位符护栏**:你写的 wiki 是用户的私有 vault,**不**在开源仓库内,真实数据可以出现 — 但不要把 vault 里的真实数据带回任何 plan / spec / commit message

## 输出

通过 `clonemate.merge_note.write()` 写入 vault/wiki/ 下的:
- `wiki/persona.md`(page_type=persona)
- `wiki/voice.md`(page_type=voice)
- `wiki/entities/<title>.md` × N(page_type=entity)
- `wiki/concepts/<title>.md` × N(page_type=concept)

每个 wiki 页严格遵循 `references/wiki-schema.md` 定义的 frontmatter:
- `page_type` / `title` / `sources`(必含至少 1 条 src_id)/ `confidence`(自评 high/medium/low)/ `needs_review`(模糊或单 source 推断时设 true)/ `pinned_fields`(初始为空)/ `last_modified` / `last_modified_by=ingest`

## 编排步骤(主对话执行)

1. Read `_clone.yaml`,记 `target_open_id = identity.open_id` 与 `display_name`
2. Read 所有 raw frontmatter,按 source_type 分组,统计每组数量
3. 按 `references/workflow-ingest.md` 的派遣矩阵派出 subagent(per source_type)
4. 等所有 subagent 完成 — 它们各自调过 `merge_note.write` 写好了自己负责的 wiki 块
5. 调 `python -m clonemate.index_upsert --vault-dir <vault> --display-name "<name>"` 重建 index.md
6. 调 `clonemate.log_append.append(log_path, op="ingest", subject="initial-ingest", metric="+N raw / +M wiki")`

## 派 subagent 时给它们的指引(共享要点)

每个 subagent 的 prompt 必须包含:
- 上面"不可越过的红线"段(原样复制)
- 它负责的 source_type + raw 文件列表(主对话提供)
- 它必须写的 wiki 页类型(workflow-ingest.md 矩阵)
- 调 `merge_note.write` 的具体调用形式
- voice 提炼时附带 `references/prompt-voice.md` 的指引

## 错误处理

- 任何 raw 文件 frontmatter 解析失败 → log warning,跳过该文件,继续
- subagent 报"无可写 wiki"(raw 太少、无信号)→ 接受,不强行写
- 同名 entity 页两个 subagent 都尝试写 → 没问题,merge_note 的 fcntl.flock 会序列化它们;后写者会读已存在的 frontmatter+body,追加自己 sources,合并 body

## 不在 M3 范围内

- Phase B 自动复核清单(M4)
- Phase C 同会话引导式确认(M4)
- Voice transfer answer(M5)
- Lint(M6)
- Forget(M6)

主对话完成上述编排后,**停**;不要主动去做 query 或 review。

## Phase B/C handoff (M4)

After running `python -m clonemate ingest-finish`:

1. Read `references/workflow-review.md` and `references/prompt-review.md`.
2. Run `python -m clonemate review --root <root> --slug <slug>`.
3. Drive the Phase C dialogue with the user (4-option per item; user can exit).
4. After dialogue ends, run `python -m clonemate review-finish ... --resolved K --skipped N`.
5. Stop after `review-finish`. M5 (`clonemate ask`) and M6 (lint / forget) are
   now available — invoke them on user intent, NOT automatically after review.
   The user may immediately ask via `clonemate ask <slug> "..."`; that's a
   separate Phase ask invocation, not a chain from review.

The user expects this auto-continuation; do **not** stop after `ingest-finish`
unless the checklist is empty (in which case tell them "无需复核" and run
`review-finish` with 0/0).
