# Install

## Prerequisites

- Python 3.10+
- `git` 与 `git-filter-repo`(vault.init 阶段检测;后者用于 forget 历史改写)
- [lark-cli](https://github.com/yeasy1003/lark-cli) ≥ 1.0.21 配置好 `claude-code` profile

```bash
brew install git-filter-repo            # macOS
# 或 pip install git-filter-repo
```

## Install from source

```bash
git clone https://github.com/yeasy1003/clonemate.git
cd clonemate
pip install -e ".[dev]"
ln -s "$(pwd)" ~/.claude-personal/skills/clonemate
```

## Verify

```bash
python -m clonemate.sanitize_check        # 应输出 OK
pytest tests/unit -q                       # 应全绿
```
