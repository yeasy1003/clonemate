# Ingest Workflow — Subagent Dispatch

> **Audience:** Claude main conversation during `clonemate ingest`.

## 派遣矩阵

| Source type | Subagent number | Wiki pages it owns |
|---|---|---|
| `contact` + `calendar` | sub-A | persona(职责 / 部门 / 汇报线 / 近期重点)+ 若干 entity(项目时间线、合作者) |
| `im_1v1` + `im_group`(ta 自己消息部分) + `minutes`(ta 段) + `comments`(author == ta) | sub-B | voice.md(完整) + 补充 persona(沟通偏好) |
| `minutes` + `docs` + `comments` | sub-C | entity 页(项目 / 团队 / 产品)+ concept 页(技术观点 / 方法论 / 立场) |
| `im_group`(高信号消息上下文,含他人) | sub-D | entity 页(协作画像:他人视角看 ta;**不**进 voice) |

## 派遣规则

1. 主对话先 Read `_clone.yaml.identity.open_id`,把 target_open_id 传给所有 subagent
2. 主对话扫 `raw/<source_type>/.hashes.txt` 与目录,按 source_type 分组 raw 列表
3. 每个 subagent 收到:
   - 它负责的 source_type 列表 + raw 文件路径列表
   - target_open_id + display_name
   - 红线段(从 prompt-ingest.md 复制)
   - 它能写的 wiki page_type 列表(参考矩阵)
   - voice subagent 额外接收 prompt-voice.md
4. **Subagents 并行**(主对话用 `Agent` tool 并发派 4 个);主对话自己**不**写 wiki
5. 所有 subagent 完成后,主对话调 `python -m clonemate.index_upsert` + `log_append`

## Subagent 间避免冲突

- 不同 subagent 写不同 wiki 页(矩阵不重叠)
- 例外:**persona** 与 **某些 entity** 可能两个 subagent 都触及。merge_note 的 per-page fcntl 锁会序列化这种重叠,后写者读老 frontmatter 与 body,把自己的 source 追加到 `sources`,自己的内容追加 / 合并到 body 对应 H2 区。**Subagents 必须遵循"读现有 wiki 页 → 在合适 H2 区下追加 / 修订自己的部分 → 调 merge_note"** 的节奏,而不是粗暴 overwrite。

## Subagent 完成报告

每个 subagent 报告:
- DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
- 它写了哪些 wiki 页(`merge_note.WriteResult.path` 列表)
- 它读了哪些 raw src_id(用于 main 对话最后做覆盖率检查 — 期望"几乎所有 raw 都至少被一个 subagent 引用")
- 任何冲突或不确定的事实(用于 M4 Phase B 复核清单的种子)

## Idempotency

主对话再次跑 `clonemate ingest` 应该:
- raw 内容未变 → wiki 内容应基本不变(M3 fixture 测试可能由于 LLM 非确定性出现轻微变化,但 frontmatter / pinned 不应变;sources 列表只增不减;structural skeleton 一致)
- raw 有新增 → 新增 src_id 进 sources;受影响 wiki 页 needs_review 可能重新设 true(M3 不强求,M4 lint 会查)

## 失败处理

- subagent BLOCKED → 主对话标记此 source_type 为待重试,**仍然**调 index_upsert 把已成功 subagent 的产出写进 index;log_append 记录失败原因
- 某 raw 文件解析失败 → subagent 跳过它,在报告里 list 失败的 src_id
