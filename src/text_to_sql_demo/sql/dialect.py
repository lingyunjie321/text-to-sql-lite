from __future__ import annotations

from typing import Literal, cast

import sqlglot
from pydantic import BaseModel
from sqlglot import exp
from sqlglot.errors import ParseError

DialectName = Literal["sqlite", "postgres", "mysql"]
SUPPORTED_DIALECTS: set[str] = {"sqlite", "postgres", "mysql"}


class DialectError(ValueError):
    """SQL 方言处理的基础异常。"""


class UnsupportedDialectError(DialectError):
    """请求了当前 demo 不支持的 SQL 方言。"""


class SQLDialectParseError(DialectError):
    """SQLGlot 无法按指定方言解析 SQL。"""


class DialectRenderResult(BaseModel):
    """SQL 标准化和方言渲染结果。"""

    source_dialect: DialectName
    target_dialect: DialectName
    normalized_sql: str
    rendered_sql: str
    transpiled: bool = False


class DialectService:
    """集中封装 SQLGlot 的方言解析、标准化和转换能力。"""

    def normalize(self, sql: str, *, dialect: str) -> DialectRenderResult:
        """按输入方言解析并输出该方言下的标准化 SQL。"""
        expression = self.parse_one(sql, dialect=dialect)
        dialect_name = self.ensure_supported(dialect)
        rendered_sql = self.render_expression(expression, dialect=dialect_name)
        return DialectRenderResult(
            source_dialect=dialect_name,
            target_dialect=dialect_name,
            normalized_sql=rendered_sql,
            rendered_sql=rendered_sql,
            transpiled=False,
        )

    def transpile(
        self,
        *,
        sql: str,
        source_dialect: str,
        target_dialect: str,
    ) -> DialectRenderResult:
        """把已有 SQL 从 source_dialect 转换到 target_dialect。"""
        source = self.ensure_supported(source_dialect)
        target = self.ensure_supported(target_dialect)
        expression = self.parse_one(sql, dialect=source)
        return DialectRenderResult(
            source_dialect=source,
            target_dialect=target,
            normalized_sql=self.render_expression(expression, dialect=source),
            rendered_sql=self.render_expression(expression, dialect=target),
            transpiled=source != target,
        )

    def parse_one(self, sql: str, *, dialect: str) -> exp.Expression:
        """按指定方言解析单条 SQL。"""
        dialect_name = self.ensure_supported(dialect)
        try:
            expressions = sqlglot.parse(sql, read=dialect_name)
        except ParseError as exc:
            raise SQLDialectParseError(str(exc)) from exc

        if len(expressions) != 1:
            raise DialectError("只允许单条 SQL 查询")
        return expressions[0]

    def render_expression(self, expression: exp.Expression, *, dialect: str) -> str:
        """把 SQLGlot 表达式渲染为目标方言 SQL。"""
        dialect_name = self.ensure_supported(dialect)
        return expression.sql(dialect=dialect_name)

    def ensure_supported(self, dialect: str) -> DialectName:
        """校验并规范化 demo 支持的 SQL 方言名称。"""
        normalized = dialect.lower().strip()
        if normalized not in SUPPORTED_DIALECTS:
            available = ", ".join(sorted(SUPPORTED_DIALECTS))
            raise UnsupportedDialectError(f"不支持的 SQL 方言: {dialect}; 可用方言: {available}")
        return cast(DialectName, normalized)
