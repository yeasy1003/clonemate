# Phase B / Phase C — Review Dialogue Prompt

> **Audience:** Claude main conversation, invoked by `clonemate review` (or
> auto-continued from `clonemate ingest-finish`).

## Phase B (already done by `review_cmd.emit_prompt`)

When you read this, the orchestration message has already listed the checklist.
Your job is **Phase C**: walk the user through each item, apply their decision.

## Per-item dialogue

For EACH item in the checklist, do this micro-loop:

1. **Show context briefly** (2-3 sentences max): the page, the section, the
   excerpt or marker. Do NOT dump the whole page.
2. **Ask the 4-option question** verbatim:

   > [A] 接受当前内容,标 confidence high
   > [B] 改一改 — 你来给新版本
   > [C] 跳过 — 留 `[需复核]`,我下次再处理
   > [D] 我补充新事实 — 你听我说

3. **Apply the decision** by calling Python helpers (NOT direct file writes). The right helper depends on the **bucket** of the current item:

   ### Bucket: Conflicts
   - **[A] 接受 v2(current)**: `merge_note.resolve_conflict(..., section_name=<name>, accepted_body=<v2 body>, decided_by_user=True)` — drops marker, keeps current.
   - **[B] 用 v1**: same call with `accepted_body=<v1 body retrieved from git>`.
   - **[C] 跳过**: do nothing.
   - **[D] 给 v3**: ask user, then `resolve_conflict(..., accepted_body=<v3>)`.
   - See `references/prompt-conflict.md` for full v1/v2/v3 sub-flow.

   ### Bucket: Needs review (frontmatter `needs_review: true`)
   - **[A] 接受**: `merge_note.apply_review_accept(..., confidence='high', pin_fields=[...] if persona core)`. Frontmatter-only — body unchanged.
   - **[B] 改**: ask user "你想改成什么?" with section name. Then call `merge_note.resolve_conflict(..., section_name=<H2>, accepted_body=<user input>, decided_by_user=True)` — this overwrites that H2 section without producing a new CONFLICT marker (Codex round 2 Finding 8). After body is correct, call `apply_review_accept` to close. **DO NOT use `merge_note.write`** — it goes through the ingest-style section-merge path that injects CONFLICT markers on H2 collisions.
   - **[C] 跳过**: do nothing.
   - **[D] 我补充**: ask user; if the new fact replaces an existing H2 section, use `resolve_conflict` (same as [B]). If it's a brand-new section that doesn't exist yet, then `merge_note.write(...)` is safe (no collision). Always finish with `apply_review_accept` to close.

   ### Bucket: Ambiguities (`> ⚠️ AMBIGUOUS:`)
   - **[A] 接受当前(用第一个解释)**: `merge_note.resolve_ambiguity(..., marker_text_substring=<excerpt>, replacement=<the chosen interpretation>, decided_by_user=True)`.
   - **[B] 改/澄清**: ask user; same call with their wording as `replacement`.
   - **[C] 跳过**: do nothing — marker stays, item resurfaces next round.
   - **[D] 删除该 marker(确认无歧义)**: `resolve_ambiguity(..., replacement="")` — drops the marker line cleanly.

   ### Bucket: Unclear topics (`> ⚠️ UNCLEAR:`)
   - **[A] 接受**: `merge_note.resolve_unclear(..., replacement=<one-sentence stance>)`. NOTE: low-confidence pages keep `needs_review=True` even after marker cleared — call `apply_review_accept(confidence='medium')` to fully close.
   - **[B] 改**: ask user; `resolve_unclear(..., replacement=<user input>)`.
   - **[C] 跳过**: do nothing.
   - **[D] 用户补充**: same as [B].

   **Key contract**: every [A/B/D] decision MUST end with the matching marker REMOVED from body (resolve_*) AND `needs_review` recomputed (helper does this automatically). [C] is the only path where the marker / needs_review survives.

4. **Confirm to user briefly**: "已接受 / 已改为 ... / 已跳过 / 已记录"

5. **Move on** to next item.

## Exit handling

- The user may say "够了 / stop / 跳过剩下的 / 下次再说" at any time.
- When they exit, count the items resolved vs. skipped, and call:
  ```
  python -m clonemate review-finish --root <root> --slug <slug> --resolved <K> --skipped <N>
  ```

## Red lines (repeat from orchestration message)

- 事实正确 > 风格化 (spec §8.5)
- 不要假装用户说过的事
- voice 内容只读不写;只可能 pin 字段
- 用户能随时退出,不要逼问

## Ordering hint

Process buckets in this order:
1. Conflicts (highest signal — explicit disagreement)
2. needs_review pages (low confidence, single-source)
3. Ambiguities (LLM saw real ambiguity)
4. Unclear topics (LLM noticed mention without commitment)

Within a bucket, persona / voice 优先(克隆体根基),然后 entity / concept / synthesis。
