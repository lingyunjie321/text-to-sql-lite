import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

QUESTION_MAX_CHARS = 2000
DEFAULT_TIMEZONE = "Asia/Shanghai"

_ENGLISH_RELATIVE_DAYS = {
    "today": 0,
    "yesterday": -1,
    "tomorrow": 1,
}
_CHINESE_RELATIVE_DAYS = {
    "今天": 0,
    "昨天": -1,
    "明天": 1,
}


@dataclass(frozen=True, slots=True)
class PreprocessedQuestion:
    normalized_question: str
    normalized_time: str | None
    requires_clarification: bool


def preprocess_question(
    question: str,
    *,
    now: datetime,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> PreprocessedQuestion:
    if (
        not isinstance(question, str)
        or not isinstance(now, datetime)
        or now.tzinfo is None
    ):
        if isinstance(question, str):
            raise ValueError("time context is invalid")
        raise ValueError("question is invalid")
    normalized = " ".join(
        unicodedata.normalize("NFKC", question).split()
    )
    if not normalized or len(normalized) > QUESTION_MAX_CHARS:
        raise ValueError("question is invalid")
    try:
        local_now = now.astimezone(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError as error:
        raise ValueError("time context is invalid") from error

    deltas = {
        delta
        for token, delta in _CHINESE_RELATIVE_DAYS.items()
        if token in normalized
    }
    folded = normalized.casefold()
    deltas.update(
        delta
        for token, delta in _ENGLISH_RELATIVE_DAYS.items()
        if re.search(rf"\b{token}\b", folded)
    )
    if len(deltas) > 1:
        return PreprocessedQuestion(
            normalized_question=normalized,
            normalized_time=None,
            requires_clarification=True,
        )
    normalized_time = None
    if deltas:
        delta = next(iter(deltas))
        normalized_time = (
            local_now.date() + timedelta(days=delta)
        ).isoformat()
    return PreprocessedQuestion(
        normalized_question=normalized,
        normalized_time=normalized_time,
        requires_clarification=False,
    )
