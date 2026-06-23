from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class BusinessDialectPattern(BaseModel):
    """业务 SQL 方言范式，用于生成阶段的 Few-shot 上下文。"""

    name: str
    dialect: str
    description: str
    pattern: str
    tags: list[str] = Field(default_factory=list)
    involved_tables: list[str] = Field(default_factory=list)


class BusinessPatternSearchResult(BaseModel):
    """业务方言范式检索结果。"""

    pattern: BusinessDialectPattern
    score: float
    reasons: list[str] = Field(default_factory=list)


class BusinessPatternStore:
    """可替换的本地业务 SQL 方言范式仓库。"""

    def __init__(self, patterns: list[BusinessDialectPattern]) -> None:
        self.patterns = patterns

    @classmethod
    def from_yaml(cls, path: str | Path) -> BusinessPatternStore:
        """从 YAML 文件加载业务方言范式。"""
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
        return cls(
            [
                BusinessDialectPattern.model_validate(item)
                for item in raw.get("patterns", [])
            ]
        )

    def search(
        self,
        *,
        query: str,
        dialect: str | None = None,
        top_k: int = 3,
        involved_tables: list[str] | None = None,
    ) -> list[BusinessPatternSearchResult]:
        """按 dialect、词法相似度和表重叠检索 Top-K 业务范式。"""
        query_terms = _tokenize(query)
        requested_tables = set(involved_tables or [])
        results: list[BusinessPatternSearchResult] = []

        for pattern in self.patterns:
            if dialect and pattern.dialect != dialect:
                continue
            pattern_terms = _tokenize(
                " ".join(
                    [
                        pattern.name,
                        pattern.description,
                        pattern.pattern,
                        *pattern.tags,
                        *pattern.involved_tables,
                    ]
                )
            )
            matched_terms = query_terms & pattern_terms
            matched_tables = requested_tables & set(pattern.involved_tables)
            score = len(matched_terms) * 2.0 + len(matched_tables) * 1.5

            reasons = []
            if matched_terms:
                reasons.append(f"词项匹配: {', '.join(sorted(matched_terms))}")
            if matched_tables:
                reasons.append(f"表重叠: {', '.join(sorted(matched_tables))}")

            if score > 0:
                results.append(
                    BusinessPatternSearchResult(
                        pattern=pattern,
                        score=round(score, 3),
                        reasons=reasons,
                    )
                )

        return sorted(
            results,
            key=lambda result: (-result.score, result.pattern.name),
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
