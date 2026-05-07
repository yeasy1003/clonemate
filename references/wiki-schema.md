# Wiki Schema

CloneMate vault 的 `wiki/` 目录由 LLM 维护。所有页面通过 `merge_note.py` 写入,**禁止**任何工具直接 `file.write_text` 到 `wiki/`。

## Page types(spec §5.5)

| `page_type` | 路径 | 用途 | sources 来源限制 |
|---|---|---|---|
| `persona` | `wiki/persona.md` | "ta 是谁":职责 / 专长 / 近期重点 / 沟通偏好 | 任意 source(优先 ta 自己产出) |
| `voice` | `wiki/voice.md` | "ta 怎么说话":句式 / 口头禅 / few-shot 范例 | **仅** im_1v1 / im_group(ta 自己消息)/ minutes(ta 段)/ doc_comments(author == target);docs 正文禁用 |
| `entity` | `wiki/entities/<title>.md` | 项目 / 团队 / 产品 / 其他人 | 任意 source |
| `concept` | `wiki/concepts/<title>.md` | 技术观点 / 方法论 / 立场 | 任意 source |
| `synthesis` | `wiki/syntheses/<title>.md` | 跨页综合 / 对比 / 问答回写 | 来自 ≥ 2 个 wiki 页(含 raw 时也要标 source) |
| `source_summary` | `wiki/sources/<src_id>.md` | 单 source 一句话摘要(M3 不强制写,可选) | 仅一个 src_id |

## Frontmatter(统一)

```yaml
---
page_type: persona | voice | entity | concept | synthesis | source_summary
title: XX 项目                        # 页面主题(persona / voice 可省略)
sources: [src-0001, src-0007, src-0019] # 引用的 raw src_id 列表
confidence: high | medium | low      # LLM 自评
needs_review: false                  # true 时进 index 待裁决区
pinned_fields: [职责, 沟通偏好]      # 用户已确认的字段;merge_note 重 ingest 时不动
last_modified: 2026-04-30T15:00:00+08:00
last_modified_by: ingest | review | query | lint | user
---
```

**校验规则**(`merge_note._validate_frontmatter` 强制):
- `page_type` 必填,且必须是上面 6 个之一
- `sources` 必填(可空 list)
- `confidence` 必填,且必须是 `high` / `medium` / `low`
- `needs_review` 是 bool(默认 false)
- `pinned_fields` 是 list[str](默认 [])
- `last_modified` 是 ISO 8601 tz-aware 字符串
- `last_modified_by` 是上面 5 个之一
- voice 页额外校验:`sources` 必须**只**指向 im_1v1 / im_group / minutes / doc_comments 的 src_id(red-line per spec §3 决策 18 / §8.5)

## Conflict 表达(spec §6.5 / §8.2)

跨页或跨 source 的矛盾用 markdown 内联块标:

```markdown
## 关键决策

- 2026-03-15 决定走 A 方案(src-0007)
- 2026-04-10 收敛到 B 方案(src-0019)

> ⚠️ CONFLICT: src-0007 与 src-0019 在性能 vs 简洁的优先级上不一致,待裁决。
```

`index_upsert` 扫此 pattern 收口到"待裁决"区。

## Voice page 特殊字段(spec §5.6)

```yaml
---
page_type: voice
title: 张三的语言风格档案
sources: [src-0001, src-0007]
few_shot_count: 12
confidence: high
needs_review: false
last_modified: 2026-04-30T15:00:00+08:00
last_modified_by: ingest
---

# 张三的语言风格档案

## 总体基调
- 简洁 / 偏理性 / 偏谨慎
- 标点:多用 "/" 分隔同类项;问号常成对;极少用 "!"

## 句式特征
...

## 高频口头禅
- "本质上"
- "这块"

## 不会出现的表达(负样本)
- 几乎不用感叹号

## 场景分段 few-shot

### §1v1 场景
- (src-0001): "嗯,我看了一下"
- (src-0001): "这块我有个不同看法"

### §群聊场景
- (src-0007): "..."

### §文档评审
- (src-0019): "..."
```

**Few-shot list item format**:`- (src-NNNN): "verbatim quote"` — `merge_note._validate_voice_body_quotes` parses this exact form to bind every quote to a `voice_evidence` entry.

约定:
- voice.md 的 `sources` **只能来自** im_1v1(`author == target`) / im_group(`author == target`,即 ta 自己发的消息,**不含**上下文 ±20 中他人消息) / minutes(ta 段逐字稿) / doc_comments(`author == target`,**不含**他人在 ta 文档下的评论)
- few-shot 范例脱敏:替换具体项目/人名,但句式/口头禅/标点完全保留
- ≥ 5 条 few-shot 才能 confidence: high

## 跨页引用约定

- 同 vault 内引用:相对路径 markdown 链接 `[XX 项目](entities/XX 项目.md)`
- 引用 raw:行内 `(src-0007)`,不写完整 URL
- raw frontmatter `origin.url` 是真实 lark 跳转入口(由 ingest 阶段从 raw 读)
