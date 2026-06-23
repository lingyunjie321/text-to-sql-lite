from typing import Literal

from pydantic import BaseModel, Field

from text_to_sql_demo.llm.models import ModelProfile

ComplexityLevel = Literal["simple", "medium", "complex"]


class ComplexityResult(BaseModel):
    """可解释的查询复杂度分类结果。"""

    level: ComplexityLevel
    score: int
    reasons: list[str] = Field(default_factory=list)
    features: dict[str, bool | int] = Field(default_factory=dict)


class ComplexityClassifier:
    """第一版规则复杂度分类器。"""

    def classify(self, question: str, linked_schema: dict) -> ComplexityResult:
        tables = linked_schema.get("tables", [])
        table_count = len(tables)
        normalized = question.lower()
        features: dict[str, bool | int] = {
            "table_count": table_count,
            "join_clue": table_count >= 2 or _contains_any(normalized, ["join", "关联"]),
            "aggregation": _contains_any(
                normalized,
                ["统计", "总", "求和", "平均", "sum", "count", "avg", "聚合"],
            ),
            "subquery": _contains_any(normalized, ["子查询", "exists", " in (", "嵌套"]),
            "cte": _contains_any(normalized, ["with ", "cte", "公共表表达式"]),
            "window": _contains_any(normalized, ["窗口", "over", "row_number", "rank"]),
            "ranking_topn": _contains_any(normalized, ["排名", "top", "前", "最高", "最多"]),
            "time_calc": _contains_any(
                normalized,
                ["同比", "环比", "按月", "按年", "最近", "过去"],
            ),
            "long_question": len(question) > 40,
        }
        score = _score_features(features)
        reasons = _build_reasons(features)

        if features["window"] or features["subquery"] or features["cte"]:
            level: ComplexityLevel = "complex"
        elif table_count >= 3 and (features["aggregation"] or features["ranking_topn"]):
            level = "complex"
        elif table_count >= 2 or features["aggregation"] or features["time_calc"]:
            level = "medium"
        else:
            level = "simple"

        return ComplexityResult(level=level, score=score, reasons=reasons, features=features)


class ModelRouter:
    """把复杂度级别映射到逻辑模型 alias。"""

    def __init__(self, *, profiles: dict[str, ModelProfile]) -> None:
        self.profiles = {
            alias: ModelProfile.model_validate(profile)
            for alias, profile in profiles.items()
        }

    def route(self, complexity: ComplexityResult) -> ModelProfile:
        alias = "light" if complexity.level == "simple" else "strong"
        if alias not in self.profiles:
            raise ValueError(f"缺少模型配置 alias: {alias}")
        return self.profiles[alias]


def _contains_any(value: str, needles: list[str]) -> bool:
    return any(needle in value for needle in needles)


def _score_features(features: dict[str, bool | int]) -> int:
    score = int(features["table_count"])
    for key, value in features.items():
        if key != "table_count" and value is True:
            score += 2
    return score


def _build_reasons(features: dict[str, bool | int]) -> list[str]:
    reasons = [f"涉及表数量: {features['table_count']}"]
    labels = {
        "join_clue": "JOIN 线索",
        "aggregation": "聚合",
        "subquery": "子查询",
        "cte": "CTE",
        "window": "窗口函数",
        "ranking_topn": "排名/Top-N",
        "time_calc": "时间计算",
        "long_question": "问题较长",
    }
    reasons.extend(label for key, label in labels.items() if features[key] is True)
    return reasons
