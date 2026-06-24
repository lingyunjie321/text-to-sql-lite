from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

import yaml
from pydantic import BaseModel, Field


class ReferenceSqlItem(BaseModel):
    """可注入 prompt 的参考 SQL 条目。"""

    name: str
    natural_language: str
    sql: str
    involved_tables: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class DocumentKnowledgeItem(BaseModel):
    """业务文档或平台文档知识片段。"""

    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class MetricItem(BaseModel):
    """指标口径条目。"""

    name: str
    description: str
    expression: str | None = None
    involved_tables: list[str] = Field(default_factory=list)


class SemanticModelItem(BaseModel):
    """语义模型条目，描述表、字段或业务语义层。"""

    name: str
    description: str
    tables: list[str] = Field(default_factory=list)


T = TypeVar("T", bound=BaseModel)


class KnowledgeSearchHit(BaseModel, Generic[T]):
    """某类知识库检索的一条命中。"""

    item: T
    score: float
    reasons: list[str] = Field(default_factory=list)


class KnowledgeSearchResult(BaseModel):
    """多路知识库检索结果。"""

    reference_sql: list[KnowledgeSearchHit[ReferenceSqlItem]] = Field(default_factory=list)
    documents: list[KnowledgeSearchHit[DocumentKnowledgeItem]] = Field(default_factory=list)
    metrics: list[KnowledgeSearchHit[MetricItem]] = Field(default_factory=list)
    semantic_models: list[KnowledgeSearchHit[SemanticModelItem]] = Field(default_factory=list)


class KnowledgeStore:
    """本地 fallback 知识库，模拟 datus 的多路 RAG 存储接口。"""

    def __init__(
        self,
        *,
        reference_sql: list[ReferenceSqlItem] | None = None,
        documents: list[DocumentKnowledgeItem] | None = None,
        metrics: list[MetricItem] | None = None,
        semantic_models: list[SemanticModelItem] | None = None,
    ) -> None:
        self.reference_sql = list(reference_sql or [])
        self.documents = list(documents or [])
        self.metrics = list(metrics or [])
        self.semantic_models = list(semantic_models or [])

    @classmethod
    def from_yaml(cls, path: str | Path) -> KnowledgeStore:
        """从 YAML 加载本地知识库条目。"""
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}

        return cls(
            reference_sql=[
                ReferenceSqlItem.model_validate(item)
                for item in raw.get("reference_sql", [])
            ],
            documents=[
                DocumentKnowledgeItem.model_validate(item)
                for item in raw.get("documents", [])
            ],
            metrics=[
                MetricItem.model_validate(item)
                for item in raw.get("metrics", [])
            ],
            semantic_models=[
                SemanticModelItem.model_validate(item)
                for item in raw.get("semantic_models", [])
            ],
        )

    def search(
        self,
        *,
        query: str,
        involved_tables: list[str] | None = None,
        top_k: int = 5,
    ) -> KnowledgeSearchResult:
        """按问题文本与表重叠检索多路知识上下文。"""
        requested_tables = set(involved_tables or [])
        return KnowledgeSearchResult(
            reference_sql=_rank_items(
                self.reference_sql,
                query=query,
                top_k=top_k,
                requested_tables=requested_tables,
                text_builder=lambda item: " ".join(
                    [item.name, item.natural_language, *item.tags, *item.involved_tables]
                ),
                table_builder=lambda item: item.involved_tables,
            ),
            documents=_rank_items(
                self.documents,
                query=query,
                top_k=top_k,
                requested_tables=requested_tables,
                text_builder=lambda item: " ".join([item.title, item.content, *item.tags]),
                table_builder=lambda item: [],
            ),
            metrics=_rank_items(
                self.metrics,
                query=query,
                top_k=top_k,
                requested_tables=requested_tables,
                text_builder=lambda item: " ".join(
                    [
                        item.name,
                        item.description,
                        item.expression or "",
                        *item.involved_tables,
                    ]
                ),
                table_builder=lambda item: item.involved_tables,
            ),
            semantic_models=_rank_items(
                self.semantic_models,
                query=query,
                top_k=top_k,
                requested_tables=requested_tables,
                text_builder=lambda item: " ".join([item.name, item.description, *item.tables]),
                table_builder=lambda item: item.tables,
            ),
        )


def _rank_items(
    items: list[T],
    *,
    query: str,
    top_k: int,
    requested_tables: set[str],
    text_builder: Callable[[T], str],
    table_builder: Callable[[T], list[str]],
) -> list[KnowledgeSearchHit[T]]:
    query_terms = _tokenize(query)
    hits: list[KnowledgeSearchHit[T]] = []
    for item in items:
        item_terms = _tokenize(text_builder(item))
        matched_terms = query_terms & item_terms
        matched_tables = requested_tables & set(table_builder(item))
        score = len(matched_terms) * 2.0 + len(matched_tables) * 2.5
        reasons = []
        if matched_terms:
            reasons.append(f"词项匹配: {', '.join(sorted(matched_terms))}")
        if matched_tables:
            reasons.append(f"表重叠: {', '.join(sorted(matched_tables))}")
        if score > 0:
            hits.append(
                KnowledgeSearchHit(
                    item=item,
                    score=round(score, 3),
                    reasons=reasons,
                )
            )

    return sorted(hits, key=lambda hit: (-hit.score, _stable_item_name(hit.item)))[:top_k]


def _stable_item_name(item: BaseModel) -> str:
    for field_name in ("name", "title"):
        value = getattr(item, field_name, "")
        if value:
            return str(value)
    return item.__class__.__name__


def _tokenize(value: str) -> set[str]:
    normalized = value.lower().replace("_", " ")
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9]*", normalized))
    cjk_phrases = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    tokens.update(cjk_phrases)
    for phrase in cjk_phrases:
        for size in range(2, min(4, len(phrase)) + 1):
            for index in range(0, len(phrase) - size + 1):
                tokens.add(phrase[index : index + size])
    return tokens
