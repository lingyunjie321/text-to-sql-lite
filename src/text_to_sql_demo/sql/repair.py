from __future__ import annotations

from text_to_sql_demo.sql.models import RepairStrategy, SQLError


def strategy_for_error(error: SQLError) -> RepairStrategy:
    """根据结构化 SQL 错误生成定向修复策略。"""
    if error.category == "syntax_error":
        return RepairStrategy(
            name="repair_syntax_error",
            focus="修复 SQL 语法结构",
            instructions=[
                "保持用户问题含义不变",
                "优先修复括号、逗号、别名、关键字顺序和函数调用",
                "输出单条只读 SELECT 查询",
            ],
            avoid=["不要新增无关表", "不要输出解释文本"],
        )

    if error.category == "unknown_table":
        table_hint = f" {error.table}" if error.table else ""
        return RepairStrategy(
            name="repair_unknown_table",
            focus="修复不存在表引用",
            instructions=[
                f"只替换不存在表{table_hint}".strip(),
                "优先从相关 Schema 中选择语义最接近的表",
                "同步更新该表的别名和 JOIN 条件",
            ],
            avoid=["不要虚构表", "不要保留不存在表名"],
        )

    if error.category == "unknown_column":
        column_hint = f" {error.column}" if error.column else ""
        return RepairStrategy(
            name="repair_unknown_column",
            focus="修复不存在字段引用",
            instructions=[
                f"只替换不存在字段{column_hint}".strip(),
                "优先从相关 Schema 中选择同表字段",
                "如果字段被表别名限定，保留正确别名后再替换字段名",
            ],
            avoid=["不要虚构字段", "不要改变聚合和过滤意图"],
        )

    if error.category == "ambiguous_column":
        column_hint = f" {error.column}" if error.column else ""
        return RepairStrategy(
            name="repair_ambiguous_column",
            focus="修复字段归属不明确",
            instructions=[
                f"为不明确字段{column_hint}补充正确表别名".strip(),
                "根据 SELECT、JOIN、WHERE、GROUP BY 的语义选择字段来源",
                "保持现有 JOIN 关系不变，除非 JOIN 条件本身引用错误",
            ],
            avoid=["不要删除必要 JOIN", "不要用 SELECT * 回避字段归属"],
        )

    if error.category == "type_mismatch":
        return RepairStrategy(
            name="repair_type_mismatch",
            focus="修复字段类型不匹配",
            instructions=[
                "检查比较、聚合和函数参数的字段类型",
                "必要时使用目标方言支持的显式 CAST",
                "保留原始过滤条件和聚合意图",
            ],
            avoid=["不要把数字字段当文本拼接", "不要移除关键过滤条件"],
        )

    if error.category == "dialect_error":
        return RepairStrategy(
            name="repair_dialect_error",
            focus="修复 SQL 方言或只读约束问题",
            instructions=[
                "改写为目标 SQL 方言支持的语法",
                "确保最终 SQL 是单条只读 SELECT 查询",
                "替换不兼容函数、分页和日期表达式",
            ],
            avoid=["不要输出写入、DDL 或多语句 SQL", "不要混用不同数据库方言"],
        )

    return RepairStrategy(
        name="repair_execution_error",
        focus="根据执行反馈修复 SQL",
        instructions=[
            "优先根据数据库执行错误定位字段、表、函数或类型问题",
            "保留用户问题含义和已校验通过的部分",
            "必要时简化表达式后重新构造正确查询",
        ],
        avoid=["不要忽略执行错误", "不要返回和当前 SQL 等价的错误 SQL"],
    )
