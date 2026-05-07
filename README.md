# CloneMate

> Build a structured local wiki for each colleague using the Karpathy LLM-Wiki methodology, then ask questions in their own voice.

CloneMate is an open-source Claude Code skill that orchestrates [lark-cli](https://github.com/yeasy1003/lark-cli) to collect a colleague's public Lark/Feishu activity, distill it into a maintained markdown vault (entities / concepts / syntheses / persona / voice), and answer questions in the colleague's tone — with a mandatory disclaimer.

## Features

- 8 自动采集源:Contact / IM 1v1 / IM 共同群聊(信号过滤) / Minutes / Docs(ta own) / 文档评论 / Calendar(标题级) / Meego(plugin)
- 投喂通道:飞书 URL / PDF / DOCX / PPTX / Markdown / 粘贴文本 / 结构化便签
- 三阶段静默闭环:静默采集 → 自动复核清单 → 同会话引导式确认
- voice transfer:答案以 ta 口吻输出 + 强制免责语
- Lint health-check + Forget(单源 / 整库)+ 增量 sync

## 隐私红线

- 采集严格继承调用方 Lark 权限,绝不提权
- vault 永不 push(默认安装 pre-push hook 拦截)
- raw 不入 git(物理删除即真删)
- 开源仓库内**仅占位符**,真实数据由 sanitize_check 拦截

## 状态

`v0.7.0` — M1–M7 全部完成:vault 骨架 + 自动采集(M2)+ ingest pipeline(M3)+ review(M4)+ ask / voice transfer(M5)+ lint / forget(M6)+ sync / feed / multi-profile(M7)。

## 安装

见 [INSTALL.md](INSTALL.md)。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。
