from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.workflow import preprocess_question


NOW = datetime(
    2026,
    7,
    28,
    10,
    30,
    tzinfo=ZoneInfo("Asia/Shanghai"),
)


def test_preprocess_normalizes_unicode_and_whitespace() -> None:
    result = preprocess_question(
        "  列出　影片\n标题  ",
        now=NOW,
    )

    assert result.normalized_question == "列出 影片 标题"
    assert result.normalized_time is None
    assert result.requires_clarification is False


@pytest.mark.parametrize(
    ("question", "expected_date"),
    [
        ("查询今天的租赁", "2026-07-28"),
        ("查询昨天的租赁", "2026-07-27"),
        ("查询明天的租赁", "2026-07-29"),
        ("rentals today", "2026-07-28"),
        ("rentals yesterday", "2026-07-27"),
        ("rentals tomorrow", "2026-07-29"),
    ],
)
def test_preprocess_resolves_relative_day(
    question: str,
    expected_date: str,
) -> None:
    result = preprocess_question(question, now=NOW)

    assert result.normalized_time == expected_date
    assert result.requires_clarification is False


def test_conflicting_relative_days_require_clarification() -> None:
    result = preprocess_question(
        "比较 today 和 yesterday 的租赁",
        now=NOW,
    )

    assert result.normalized_time is None
    assert result.requires_clarification is True


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_invalid_question_is_rejected(question: str) -> None:
    with pytest.raises(ValueError, match="question is invalid"):
        preprocess_question(question, now=NOW)


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="time context is invalid"):
        preprocess_question(
            "rentals today",
            now=datetime(2026, 7, 28),
        )
