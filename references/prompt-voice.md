# Voice 提炼 Prompt

> **Audience:** subagent dispatched by main conversation during ingest.
> Use together with `references/prompt-ingest.md` red-line block.

## 你的任务

从给定的 raw 文件集合(仅来自 im_1v1 / im_group / minutes / doc_comments)中,**仅提取 author_open_id == target.open_id 的部分**,产出 `wiki/voice.md`。

## 红线(必读)

- **Author 过滤**:跳过任何 `author_open_id != target.open_id` 的内容;群聊里别人 @ ta 的消息不能进 voice
- **来源类型**:不要读 `raw/docs/`(那是正式文档,语气与日常对话差别大)
- **事实正确 > 风格化**:few-shot 范例必须真实出现在 raw 中,不要发明
- **脱敏**:few-shot 把具体项目名 / 人名替换为占位符,但句式 / 标点 / 口头禅完全保留

## 输出 schema(spec §5.6)

通过 `merge_note.write(page_type='voice', source_types_map={...})` 写入(注意必须传 source_types_map,merge_note 会强制校验来源)。

frontmatter 必含:
- `page_type: voice`
- `sources: [src-NNNN, ...]`
- `few_shot_count: <int>` ≥ 5 才能 confidence: high
- `confidence: high|medium|low`
- `needs_review: true` 当 sources 太少或仅一种场景

body 章节(单一 H1 page title + H2 sections + H3 子分段):

```markdown
# {{ display_name }} 的语言风格档案

## 总体基调

(2-4 句,描述基调:简洁/冗长、理性/感性、严肃/调侃……)

## 句式特征

- 开场常用:"..."
- 表达异议:"..."
- 收束:"..."
- 决策表达:"..."

## 高频口头禅

(从 raw 频次统计 top 10)
- "..."

## 不会出现的表达(负样本)

(如果观察到明确的禁忌)
- 极少用 "!"
- 不会说 "绝对" / "一定"

## 场景分段 few-shot

### §1v1 场景

- (src-NNNN): "脱敏后的引文 — 必须与 voice_evidence 中某条 quote 完全或子串匹配"
- (src-NNNN): "..."

### §群聊场景

- (src-NNNN): "..."

### §文档评审

- (src-NNNN): "..."
```

**关键格式契约**(被 `merge_note._validate_voice_body_quotes` 解析):

- 每个 `§...` 子分段(H3 或 H2 含 "场景"/"§" 字样)下的 list item 必须形如 `- (src-NNNN): "verbatim quote"`
- `src-NNNN` 必须在 `voice_evidence` 中,该 evidence 的 `author_open_id == target_open_id`
- `quote` 必须是 evidence 中某条 quote 的子串(支持脱敏后切片)
- 不符合该格式的 list item / 引用未知 src 的 list item → `merge_note` raise `VoiceSourceViolation`

## 调 merge_note 的形式(强制契约 — Codex Findings 1+9)

```python
from clonemate import merge_note

merge_note.write(
    vault_dir=Path(vault_dir),
    page_type="voice",
    title=None,                                     # voice page omits title in frontmatter
    sources=collected_src_ids,                      # list[str]
    source_types_map=collected_source_types,        # dict[src_id, source_type] — REQUIRED
    target_open_id=target_open_id,                  # ta 的 open_id — REQUIRED
    voice_evidence=evidence_records,                # list[{src_id, author_open_id, quote}] — REQUIRED
    confidence="medium",                            # 自评
    needs_review=(len(evidence_records) < 5),       # < 5 few-shots → needs_review
    body=assembled_body,
    author_role="ingest",
    extra_frontmatter={"few_shot_count": len(evidence_records)},
)
```

`evidence_records` 的每一条必含三个字段:
- `src_id`: 引用的 raw src_id(必须在 source_types_map 里)
- `author_open_id`: 该引用句的真实作者 open_id(**必须 == target_open_id**,否则 merge_note 会 raise VoiceSourceViolation)
- `quote`: 真实出现在该 raw 中的脱敏后引文

如果你试图把他人句子放进 voice few-shot,merge_note 会拒绝写入。**这条红线现在在代码层强制,不依赖你配合**。

## 不要做

- 不要从 docs 正文 raw 里抽 voice
- 不要把 ta 同事的话归到 ta(作者归属红线 — 代码强制)
- 不要写"通过分析,推测他可能..."这种没有 raw 引用的句子
