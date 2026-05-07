---
name: clonemate
version: 0.2.0
description: "Build, refresh, and query a structured local wiki for each colleague using the Karpathy LLM-Wiki methodology. TRIGGER on: clone <人>, sync <人>, 问 <人>..., ask <name>..., 让<人>回答..., <人>会怎么说..., 我克隆了谁, list clones, clonemate <subcommand>."
metadata:
  requires:
    bins: ["lark-cli", "git", "git-filter-repo"]
---

# CloneMate Skill

> 把每个同事的飞书痕迹蒸馏成可问答的本地 wiki — 仿语气、有引用、永不出本地。

## When to Use

任意以下意图(中英混用都行)→ 启动这个 skill:

- **建克隆体**:`clone 张三` / `克隆马佳和` / `clonemate clone <handle>` — 第一次抓数据 + ingest + review
- **更新克隆体**:`sync 张三` / `更新马佳和的资料` — 增量拉新数据
- **问克隆体**:**`问马佳和 周五能 CR 吗?`** / **`ask majiahe how to split the knowledge base?`** / `让张三回答 ...` / `<名字>会怎么说...`
- **看你克隆了谁**:`我克隆了谁` / `list clones` / `clonemate list`
- **手动投喂**:`feed 马佳和 这条消息: ...` / `把这个文档加到张三的 wiki`
- **复核 / 编辑**:`review 马佳和` / `重新看一下张三的 wiki`
- **删除**:`forget 马佳和` / `删除张三的克隆体`

## 默认 vault 路径

`~/obsidian/clonemate`(可被 `CLONEMATE_ROOT` 环境变量覆盖)。本 skill 默认就用这个,**不用每次问用户路径**。

## "问 X" 工作流(最常用 — 务必会)

用户说 **"问 <名字> ..."** / **"ask <name> ..."** / **"让 <名字> 回答 ..."** / **"<名字>会怎么说"** 时:

1. **解析 display_name → slug**:
   ```bash
   python3 -m clonemate.vault list --root ~/obsidian/clonemate
   ```
   找 `display_name == <名字>` 那一行,取 slug。**不要让用户敲 slug,也不要问"是哪个张三"** — 如果只一个匹配直接用,多个匹配时才让用户挑。
2. **跑 ask**:
   ```bash
   python3 -m clonemate ask \
     --root ~/obsidian/clonemate \
     --slug <slug> \
     --question "<verbatim question>"
   ```
   它会输出 orchestration prompt(不要把 prompt 全文显示给用户),你按 prompt 走 4a/4b/4c 三步:事实合成 → voice transfer → 加免责语。
3. **直接把克隆体回复 + 免责语贴给用户**(不要解释流程,除非用户问)。
4. **跑 ask-finish**:
   ```bash
   python3 -m clonemate ask-finish \
     --root ~/obsidian/clonemate \
     --slug <slug> \
     --question "<verbatim question>" \
     --synthesis-written 0
   ```

如果回答跨了 ≥2 个 wiki 页或形成新 stance,设 `--synthesis-written 1 --synthesis-title "<short title>"` 并先 `merge_note.write` 一个 synthesis 页(见 references/prompt-query.md)。默认 0。

## "克隆 X" 工作流

用户说 **"clone 张三"** / **"克隆马佳和"**(handle 可以是中文姓名 / 邮箱 / open_id)→

1. **拿你自己的 my_open_id**(从 `lark-cli --profile claude-code config show` 的 userOpenId 字段,或之前已经知道)
2. **跑 clone**:
   ```bash
   python3 -m clonemate clone "<handle>" \
     --root ~/obsidian/clonemate \
     --my-open-id <ou_xxxx> \
     --since 30d
   ```
   失败常见原因:中文姓名没法生成 ASCII slug → 自动 fallback 到 email local-part。
3. clone 成功后**自动接 ingest**:`python3 -m clonemate ingest --root ... --slug <new-slug>` → 派 3-4 个 subagent 写 wiki → `ingest-finish`。
4. ingest 完接 review:`python3 -m clonemate review` → Phase B 列 needs-review 项 → Phase C 跟用户走 4-option(`[A] 接受 [B] 改 [C] 跳 [D] 我补充`)→ `review-finish`。
5. 完成后告诉用户"<名字> 克隆完成,可以问任何问题了"。

## 红线(永不可越过)

1. 采集严格继承调用方 Lark 权限,绝不提权
2. calendar 仅取 summary / time / participants
3. **vault 永不出本地**(pre-push hook 拦截)
4. **forget 即真删**:raw 不入 git,Level2 走 git filter-repo
5. **事实正确 > 风格化**:voice transfer 只重写措辞
6. **作者归属**:voice/persona 仅取 `author == target`
7. **占位符护栏**:仓库内不含真实数据,sanitize_check 三道防线

## 子命令完整参考

```bash
# 第一次建克隆体(自动接 ingest + review)
python3 -m clonemate clone "<姓名/邮箱/open_id>" --root <root> --my-open-id <ou_xxx> [--since 180d] [--slug <ascii>]

# 增量更新
python3 -m clonemate sync --root <root> --slug <slug> --my-open-id <ou_xxx> [--source <name>] [--retry-failed] [--since <window>]

# Ingest 阶段(主 conversation 派 subagent)
python3 -m clonemate ingest --root <root> --slug <slug>
python3 -m clonemate ingest-finish --root <root> --slug <slug> --raw-count <N> --wiki-count <M>

# 复核阶段
python3 -m clonemate review --root <root> --slug <slug>
python3 -m clonemate review-finish --root <root> --slug <slug> --resolved <K> --skipped <N>

# 提问
python3 -m clonemate ask --root <root> --slug <slug> --question "..." [--literal | --voice-only]
python3 -m clonemate ask-finish --root <root> --slug <slug> --question "..." --synthesis-written 0|1 [--synthesis-title "..."]

# 投喂外部内容
python3 -m clonemate feed --root <root> --slug <slug> --input <path/url/-> [--fact "..." --confidence high|medium|low --title "..."]
python3 -m clonemate feed-finish --root <root> --slug <slug> --written <N>

# Lint / Forget / Undo / Rebind
python3 -m clonemate lint --root <root> --slug <slug>
python3 -m clonemate forget --root <root> --slug <slug> [--source <id> | --hard --yes-i-mean-it | --yes]
python3 -m clonemate undo --root <root> --slug <slug>
python3 -m clonemate rebind --root <root> --slug <slug> --profile <new>

# Vault 元操作
python3 -m clonemate.vault init --root <root> --slug <slug> --open-id <ou> --app-id <cli> --display-name "..."
python3 -m clonemate.vault list --root <root>
python3 -m clonemate.vault rename --root <root> --old-slug <old> --new-slug <new>

# Sanitize 自检(确保仓库本身不含真实数据)
python3 -m clonemate.sanitize_check .
```

## References

- [references/prompt-ingest.md](references/prompt-ingest.md) / [workflow-ingest.md](references/workflow-ingest.md) — ingest 4-subagent 派遣矩阵
- [references/prompt-review.md](references/prompt-review.md) — Phase B/C 4-option 对话
- [references/prompt-query.md](references/prompt-query.md) — ask 4a/4b/4c 三步
- [references/prompt-voice.md](references/prompt-voice.md) — voice 提炼红线
- [references/wiki-schema.md](references/wiki-schema.md) — wiki 页 frontmatter
- [references/placeholders.md](references/placeholders.md) — 占位符规范
- [CONTRIBUTING.md](CONTRIBUTING.md) — 隐私红线 PR 流程
