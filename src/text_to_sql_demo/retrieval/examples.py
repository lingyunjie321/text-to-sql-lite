from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SqlExample(BaseModel):
    """本地历史 Text-to-SQL 示例。"""

    natural_language: str
    sql: str
    dialect: str
    tags: list[str] = Field(default_factory=list)
    involved_tables: list[str] = Field(default_factory=list)


class ExampleSearchResult(BaseModel):
    """历史示例检索结果。"""

    example: SqlExample
    score: float
    reasons: list[str] = Field(default_factory=list)


class ExampleStore:
    """可替换的本地历史 SQL 示例仓库。"""

    def __init__(self, examples: list[SqlExample]) -> None:
        self.examples = examples

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExampleStore:
        """从 YAML 文件加载历史示例。"""
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
        return cls([SqlExample.model_validate(item) for item in raw.get("examples", [])])

    def search(
        self,
        *,
        query: str,
        dialect: str | None = None,
        top_k: int = 5,
        involved_tables: list[str] | None = None,
    ) -> list[ExampleSearchResult]:
        """按 dialect、词法相似度和表重叠检索 Top-K 示例。"""
        query_terms = _tokenize(query)
        requested_tables = set(involved_tables or [])
        results: list[ExampleSearchResult] = []

        for example in self.examples:
            if dialect and example.dialect != dialect:
                continue
            example_terms = _tokenize(
                " ".join([example.natural_language, *example.tags, *example.involved_tables])
            )
            matched_terms = query_terms & example_terms
            matched_tables = requested_tables & set(example.involved_tables)
            score = len(matched_terms) * 2.0 + len(matched_tables) * 1.5
            if query == example.natural_language:
                score += 5.0

            reasons = []
            if matched_terms:
                reasons.append(f"词项匹配: {', '.join(sorted(matched_terms))}")
            if matched_tables:
                reasons.append(f"表重叠: {', '.join(sorted(matched_tables))}")

            if score > 0:
                results.append(
                    ExampleSearchResult(
                        example=example,
                        score=round(score, 3),
                        reasons=reasons,
                    )
                )

        return sorted(
            results,
            key=lambda result: (-result.score, result.example.natural_language),
        )[:top_k]


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
