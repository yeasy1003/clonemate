# Placeholders Spec

仓库内所有提交内容仅允许以下占位符。任何真实数据由 `sanitize_check` 拦截。

## 人名
- 中文:`张三 / 李四 / 王五`
- 英文:`Alice / Bob / Carol`

## 项目 / 团队
- 项目:`XX 项目 / YY 项目 / ZZ 项目`
- 团队:`A 团队 / Y 团队 / Z 团队`

## 邮箱域
仅允许:`@example.com / @example.org / @example.cn / @example.io / @example.test`

## Lark 类 ID(全 x 占位)
- open_id:`ou_xxxxxxxxxxxxxxxx`
- chat_id:`oc_xxxxxxxxxxxxxxxx`
- app_id:`cli_xxxxxxxxxxxxxxxx`
- union_id:`on_xxxxxxxxxxxxxxxx`
- message_id:`om_xxxxxxxxxxxxxxxx`
- object_id:`obj_xxxxxxxxxxxxxxxx`

## 文档 / 媒体 token(全 X 占位)
- docx:`doxcnXXXXXXXXXXXX`
- wiki:`wikcnXXXXXXXXXXXX`
- sheet:`shtcnXXXXXXXXXXXX`
- base/bitable:`bascnXXXXXXXXXXXX`
- minute:`mmXXXXXXXXXXXX`
- file box:`boxcnXXXXXXXXXXXX`

## 行级豁免

确实需要写真实模式的演示(如 README 里举例 deny 规则),用 `<!-- sanitize: allow-line <reason> -->` 同行豁免。豁免必须 reviewer 双签。

## 不允许出现的内容

- 真实姓名(本人 / 同事 / 客户)
- 真实邮箱(任何非 `@example.*` 域)
- 真实 ID / token / 文档链接
- 18 位身份证号
- 11 位中国手机号(开头 1)
