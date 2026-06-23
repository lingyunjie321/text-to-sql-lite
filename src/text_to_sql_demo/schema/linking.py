from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from text_to_sql_demo.schema.catalog import DatabaseSchemaMetadata, TableMetadata

DEFAULT_TABLE_DESCRIPTIONS = {
    "regions": "地区 区域 市场 地理分区",
    "customers": "客户 顾客 买家 所属地区 区域",
    "orders": "订单 交易 销售 订单金额 下单记录",
    "order_items": "订单明细 商品数量 单价 明细行",
    "products": "商品 产品 SKU 品类 单价",
}

DEFAULT_COLUMN_DESCRIPTIONS = {
    "regions.name": "地区名称 区域名称",
    "customers.region_id": "客户所属地区 外键",
    "customers.name": "客户姓名",
    "customers.email": "客户邮箱",
    "orders.customer_id": "下单客户 外键",
    "orders.order_date": "订单日期 下单日期",
    "orders.status": "订单状态",
    "orders.amount": "订单金额 销售额 总金额",
    "order_items.order_id": "订单外键",
    "order_items.product_id": "商品外键",
    "order_items.quantity": "购买数量 商品数量",
    "order_items.unit_price": "成交单价",
    "order_items.line_total": "明细金额 行金额",
    "products.name": "商品名称 产品名称",
    "products.category": "商品品类 产品类别",
    "products.unit_price": "商品单价",
}

QUERY_SYNONYMS = {
    "地区": {"region", "regions", "region_id", "地区", "区域"},
    "区域": {"region", "regions", "region_id", "地区", "区域"},
    "客户": {"customer", "customers", "customer_id", "客户", "顾客"},
    "顾客": {"customer", "customers", "customer_id", "客户", "顾客"},
    "订单": {"orders", "order_id", "订单", "下单"},
    "金额": {"amount", "total_amount", "line_total", "金额", "销售额"},
    "销售额": {"amount", "total_amount", "line_total", "金额", "销售额"},
    "商品": {"product", "products", "product_id", "商品", "产品"},
    "产品": {"product", "products", "product_id", "商品", "产品"},
    "数量": {"quantity", "数量"},
    "统计": {"count", "sum", "total", "统计"},
}


class LinkedColumn(BaseModel):
    """字段级 Schema Linking 命中结果。"""

    name: str
    type: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class LinkedTable(BaseModel):
    """表级 Schema Linking 命中结果。"""

    name: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    columns: dict[str, LinkedColumn] = Field(default_factory=dict)


class SchemaLinkResult(BaseModel):
    """Schema Linking 输出，供下游 prompt pruning 使用。"""

    query: str
    tables: list[LinkedTable] = Field(default_factory=list)


@dataclass
class _TableScore:
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    column_scores: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    column_reasons: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


class SchemaLinker:
    """可解释的轻量 Schema Linking 实现。"""

    def __init__(self, *, top_k_tables: int = 5, max_columns_per_table: int = 8) -> None:
        self.top_k_tables = top_k_tables
        self.max_columns_per_table = max_columns_per_table

    def link(self, query: str, schema: DatabaseSchemaMetadata | dict) -> SchemaLinkResult:
        """根据问题文本为表和字段打分，并返回 Top-K 相关 Schema。"""
        schema_metadata = DatabaseSchemaMetadata.model_validate(schema)
        query_terms = _expand_query_terms(query)
        table_scores = {
            table_name: self._score_table(table, query_terms)
            for table_name, table in schema_metadata.tables.items()
        }
        self._apply_foreign_key_expansion(schema_metadata, table_scores)

        ranked_tables = sorted(
            table_scores.items(),
            key=lambda item: (-item[1].score, item[0]),
        )
        linked_tables = [
            self._build_linked_table(schema_metadata.tables[table_name], table_score)
            for table_name, table_score in ranked_tables[: self.top_k_tables]
            if table_score.score > 0
        ]

        return SchemaLinkResult(query=query, tables=linked_tables)

    def _score_table(self, table: TableMetadata, query_terms: set[str]) -> _TableScore:
        table_score = _TableScore()
        table_text = _normalize_text(
            " ".join(
                [
                    table.name,
                    table.description or "",
                    DEFAULT_TABLE_DESCRIPTIONS.get(table.name, ""),
                ]
            )
        )

        table_name_matches = _matched_terms(query_terms, table.name)
        if table_name_matches:
            table_score.score += 4.0
            table_score.reasons.append(f"表名匹配: {', '.join(sorted(table_name_matches))}")

        description_matches = _matched_terms(query_terms, table_text)
        if description_matches:
            table_score.score += 2.0
            table_score.reasons.append(f"表描述匹配: {', '.join(sorted(description_matches))}")

        column_score_cap = 3.0
        column_score_total = 0.0
        for column_name, column in table.columns.items():
            qualified_name = f"{table.name}.{column_name}"
            column_text = _normalize_text(
                " ".join(
                    [
                        column_name,
                        column.description or "",
                        DEFAULT_COLUMN_DESCRIPTIONS.get(qualified_name, ""),
                    ]
                )
            )
            name_matches = _matched_terms(query_terms, column_name)
            description_matches = _matched_terms(query_terms, column_text)

            if name_matches:
                table_score.column_scores[column_name] += 1.2
                table_score.column_reasons[column_name].append(
                    f"字段名匹配: {', '.join(sorted(name_matches))}"
                )
            if description_matches:
                table_score.column_scores[column_name] += 0.8
                table_score.column_reasons[column_name].append(
                    f"字段描述匹配: {', '.join(sorted(description_matches))}"
                )

            column_score_total += min(table_score.column_scores[column_name], 1.5)

        table_score.score += min(column_score_total, column_score_cap)
        return table_score

    def _apply_foreign_key_expansion(
        self,
        schema: DatabaseSchemaMetadata,
        table_scores: dict[str, _TableScore],
    ) -> None:
        high_signal_tables = {
            table_name
            for table_name, table_score in table_scores.items()
            if table_score.score >= 4.0
        }
        expansion_counts: dict[str, int] = defaultdict(int)
        for table_name, table in schema.tables.items():
            for foreign_key in table.foreign_keys:
                related_pairs = [
                    (table_name, foreign_key.referred_table),
                    (foreign_key.referred_table, table_name),
                ]
                for source_table, target_table in related_pairs:
                    if source_table in high_signal_tables and target_table in table_scores:
                        table_scores[target_table].score += 1.0
                        expansion_counts[target_table] += 1
                        table_scores[target_table].reasons.append(
                            f"外键扩展: {source_table} -> {target_table}"
                        )
                        for column_name in [
                            *foreign_key.constrained_columns,
                            *foreign_key.referred_columns,
                        ]:
                            if column_name in schema.tables[target_table].columns:
                                table_scores[target_table].column_scores[column_name] += 0.5
                                table_scores[target_table].column_reasons[column_name].append(
                                    f"外键关联字段: {source_table}"
                                )
        for table_name, expansion_count in expansion_counts.items():
            if expansion_count >= 2:
                table_scores[table_name].score += 1.0
                table_scores[table_name].reasons.append("多跳桥接表: 连接多个高相关表")

    def _build_linked_table(self, table: TableMetadata, score: _TableScore) -> LinkedTable:
        ranked_columns = sorted(
            score.column_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        selected_columns = ranked_columns[: self.max_columns_per_table]
        columns = {
            column_name: LinkedColumn(
                name=column_name,
                type=table.columns[column_name].type,
                score=column_score,
                reasons=score.column_reasons[column_name],
            )
            for column_name, column_score in selected_columns
            if column_score > 0
        }
        return LinkedTable(
            name=table.name,
            score=round(score.score, 3),
            reasons=score.reasons,
            columns=columns,
        )


def _normalize_text(value: str) -> str:
    return value.lower().replace("_", " ")


def _expand_query_terms(query: str) -> set[str]:
    normalized_query = _normalize_text(query)
    terms = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", normalized_query))
    for phrase, synonyms in QUERY_SYNONYMS.items():
        if phrase in query:
            terms.update(synonyms)
    terms.update(_cjk_ngrams(query, min_size=2, max_size=4))
    return {term.lower().replace("_", " ") for term in terms if term.strip()}


def _cjk_ngrams(value: str, *, min_size: int, max_size: int) -> set[str]:
    cjk_chars = "".join(re.findall(r"[\u4e00-\u9fff]", value))
    grams: set[str] = set()
    for size in range(min_size, max_size + 1):
        for index in range(0, max(len(cjk_chars) - size + 1, 0)):
            grams.add(cjk_chars[index : index + size])
    return grams


def _matched_terms(query_terms: set[str], candidate_text: str) -> set[str]:
    normalized_candidate = _normalize_text(candidate_text)
    return {
        term
        for term in query_terms
        if term and term in normalized_candidate
    }
