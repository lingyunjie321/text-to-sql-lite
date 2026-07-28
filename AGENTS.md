## Text-to-SQL 项目规格读取规则

本仓库的 Text-to-SQL MVP 以以下文件为准：

1. `docs/Text-to-SQL项目复现规格.md`
2. `docs/Text-to-SQL测试与验收规格.md`
3. `evaluation/cases/pagila_mvp.jsonl`

开始任何 Text-to-SQL 功能开发、修改、重构或测试任务前：

1. 先阅读 `docs/Text-to-SQL项目复现规格.md` 开头的“# MVP 编码入口”。
2. 根据当前任务，阅读主规格中对应模块的章节。
3. 涉及测试、验收、安全、错误路由或 Gold Case 时，必须阅读
   `docs/Text-to-SQL测试与验收规格.md` 的相关章节。
4. 涉及 Pagila E2E 时，必须读取
   `evaluation/cases/pagila_mvp.jsonl`。
5. `docs/Text-to-SQL原项目参考信息.md` 不是编码需求。
   只有在需要了解原项目背景、历史方案或技术取舍时才读取，
   不得从中直接新增 MVP 功能。
6. 如果代码实现与主规格或测试规格冲突，应以主规格和测试规格为准，
   并在修改代码前指出冲突。
7. 不需要每次全文阅读所有文档，只需读取 MVP 编码入口和当前任务相关章节。
8. 注意⚠️：后续提交代码推仓时，不可推Text-to-SQL原项目参考信息.md