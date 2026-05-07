# Contributing

## 隐私红线(不可妥协)

1. **PR 必须通过 `python -m clonemate.sanitize_check`**。CI 也会跑;fail 即 block。
2. **不接受真实数据 PR**(真实 open_id / chat_id / app_id / 邮箱 / 文档 token / 个人信息)。所有示例使用 `张三 / 李四 / XX 项目 / @example.com`。
3. 修改隐私红线相关代码(no-push hook、calendar 字段白名单、严格继承用户权限)需举证 + reviewer 双签。
4. 增加 source plugin → 必须带占位符 fixture + integration test。
5. 修改 voice schema → 必须更新 ground-truth fixture 并通过 voice fidelity 测试。

## 开发流程

```bash
pip install -e ".[dev]"
pre-commit install
pytest tests/unit -q
```

## 占位符规范

见 [references/placeholders.md](references/placeholders.md)。
