# Phase lint — Dynamic Scan Rubric

> **Audience:** Claude main conversation, invoked by `clonemate lint <slug>`.

## What you have

The orchestration message lists the static findings (orphan / missing-sources
/ dead-refs / 90d-stale). Your job is the **dynamic** pass — issues the
static scanners can't see.

## Dynamic dimensions

For each dimension, list findings (terse, with file paths). Don't surface
fixes; the user will decide via `clonemate review` or `clonemate forget`.

### 1. 跨页矛盾

Same fact stated differently across two wiki pages. Example: persona says
"喜欢 lite-RAG", concept page on RAG says "倾向 full-RAG."

Method: read each entity / concept page; cross-check claims against
related pages (use frontmatter `sources` overlap as a hint).

### 2. 缺失概念页

Recurring entity / concept mentioned ≥3 times across wiki without its own
dedicated page.

Method: build a frequency map of capitalized noun-phrases / project names
across persona / entities / syntheses; flag any with count ≥3 that lack
a `wiki/concepts/<name>.md`.

### 3. 缺失交叉引用

Concept page X mentions entity Y but Y page doesn't mention X.

Method: walk concept pages, extract entity mentions, verify the entity's
page mentions the concept back.

### 4. source 缺口

Frontmatter sources claim coverage of a topic but body has no inline
src-XXX citation for that topic.

Method: for each H2 section, check if at least one src-XXX is cited
inline; if not, flag.

## Format

Surface findings as a Markdown report:

```
## 跨页矛盾 (N)
- ...

## 缺失概念页 (N)
- ...

## 缺失交叉引用 (N)
- ...

## source 缺口 (N)
- ...
```

If a dimension is clean, write `(none)`.

## Don't

- Don't auto-fix. Lint is read-only — surface findings; user decides.
- Don't write to wiki/voice.md (M3 voice red line).
- Don't include the user's question text — lint is autonomous, not Q&A.

## Finish

After surfacing findings:

  python -m clonemate lint-finish --root <root> --slug <slug> --findings <N>

`<N>` = total static + dynamic count.
