import re

_SQL_FENCE_LABELS = frozenset({"", "sql", "sqlite", "postgres", "postgresql", "mysql"})
_FENCED_SQL_PATTERN = re.compile(
    r"```[ \t]*(?P<label>[^\n`]*)\n(?P<body>.*?)\n?```",
    re.IGNORECASE | re.DOTALL,
)


def clean_llm_sql_output(text: str) -> str:
    """从 LLM 输出中提取裸 SQL，避免 Markdown 包装干扰后续校验。"""
    candidate = text.strip()
    if not candidate:
        return candidate

    for match in _FENCED_SQL_PATTERN.finditer(candidate):
        label = _first_fence_label_token(match.group("label"))
        if label in _SQL_FENCE_LABELS:
            return match.group("body").strip()

    return candidate


def _first_fence_label_token(label: str) -> str:
    """读取代码块语言标记的首个 token，兼容 ```sql title 这类输出。"""
    normalized = label.strip().lower()
    if not normalized:
        return ""
    return normalized.split(maxsplit=1)[0]
