from __future__ import annotations

import base64
import binascii
import hashlib
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from pydantic import ValidationError

from evaluation.models import (
    CaseCategory,
    Difficulty,
    EvaluationCase,
    ExpectedBehavior,
    RetrievalRoutingCase,
    RetrievalRoutingSuiteRole,
)

CASES_INITIAL_SHA256 = (
    "049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22"
)
CASES_STATUS_NEUTRAL_SHA256 = (
    "a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7"
)
_EXPECTED_CATEGORY_COUNTS = {
    CaseCategory.SINGLE_TABLE: 5,
    CaseCategory.MULTI_JOIN: 4,
    CaseCategory.AGGREGATION: 3,
    CaseCategory.TIME: 1,
    CaseCategory.ANTI_JOIN: 1,
    CaseCategory.PERMISSION: 1,
    CaseCategory.DANGEROUS_SQL: 2,
    CaseCategory.REFLECTION: 1,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_lines(path: Path) -> tuple[bytes, list[dict[str, object]]]:
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
        raw_lines = text.splitlines()
        if (
            not payload
            or not text.endswith("\n")
            or any(not line.strip() for line in raw_lines)
        ):
            raise ValueError
        items = [json.loads(line) for line in raw_lines]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("evaluation case suite is invalid") from None
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("evaluation case suite is invalid")
    return payload, items


def _status_neutral_payload(items: list[dict[str, object]]) -> bytes:
    neutral_lines: list[str] = []
    for source in items:
        item = dict(source)
        if "status" not in item:
            raise ValueError("evaluation case suite is invalid")
        item.pop("status")
        neutral_lines.append(
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return ("\n".join(neutral_lines) + "\n").encode("utf-8")


def _normalized_payload(items: list[dict[str, object]]) -> bytes:
    return (
        "\n".join(
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for item in items
        )
        + "\n"
    ).encode("utf-8")


def status_neutral_sha256(path: Path) -> str:
    _, items = _read_lines(path)
    return _sha256_bytes(_status_neutral_payload(items))


@dataclass(frozen=True, slots=True)
class LoadedCaseSuite:
    cases: tuple[EvaluationCase, ...]
    file_sha256: str
    status_neutral_sha256: str

    @property
    def executable_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(
            case
            for case in self.cases
            if case.expected_behavior is ExpectedBehavior.EXECUTE
        )

    @property
    def security_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(
            case
            for case in self.cases
            if case.expected_behavior is ExpectedBehavior.REJECT
        )


@dataclass(frozen=True, slots=True)
class LoadedRetrievalRoutingSuite:
    role: RetrievalRoutingSuiteRole
    namespace: str
    cases: tuple[RetrievalRoutingCase, ...]
    raw_sha256: str
    normalized_sha256: str


@dataclass(frozen=True, slots=True)
class LoadedRetrievalRoutingSuites:
    development: LoadedRetrievalRoutingSuite
    calibration: LoadedRetrievalRoutingSuite


def _normalized_contamination_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    without_format_controls = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    )
    return " ".join(without_format_controls.split())


def _decoded_text_variants(value: str) -> frozenset[str]:
    pending = [value]
    observed: set[str] = set()
    for _ in range(2):
        next_pending: list[str] = []
        for candidate in pending:
            normalized = _normalized_contamination_text(
                candidate
            )
            if normalized:
                observed.add(normalized)
            decoded_values: list[str] = []
            url_decoded = unquote(candidate)
            if url_decoded != candidate:
                decoded_values.append(url_decoded)
            try:
                decoded_values.append(
                    base64.b64decode(
                        candidate,
                        validate=True,
                    ).decode("utf-8")
                )
            except (
                binascii.Error,
                UnicodeDecodeError,
                ValueError,
            ):
                pass
            try:
                if (
                    len(candidate) % 2 == 0
                    and candidate
                    and all(
                        character in "0123456789abcdefABCDEF"
                        for character in candidate
                    )
                ):
                    decoded_values.append(
                        bytes.fromhex(candidate).decode("utf-8")
                    )
            except (UnicodeDecodeError, ValueError):
                pass
            next_pending.extend(decoded_values)
        pending = next_pending
    return frozenset(observed)


def _normalized_identifier(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()
    return normalized.replace('"', "").replace("`", "")


def _normalized_join(value: str) -> str:
    left, right = value.split("=")
    return "=".join(
        sorted(
            (
                _normalized_identifier(left),
                _normalized_identifier(right),
            )
        )
    )


def _json_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(
            item
            for nested in value.values()
            for item in _json_strings(nested)
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            item
            for nested in value
            for item in _json_strings(nested)
        )
    return ()


def _gold_case_text_values(
    case: EvaluationCase,
) -> tuple[str, ...]:
    return (
        case.case_id,
        case.status.value,
        case.category.value,
        case.question,
        case.datasource_id,
        case.dialect,
        case.expected_behavior.value,
        case.expected_final_status.value,
        *(
            (case.expected_error_type.value,)
            if case.expected_error_type is not None
            else ()
        ),
        case.gold_sql,
        case.gold_result_source.value,
        case.comparison_mode.value,
        case.difficulty.value,
        *case.tags,
        *_json_strings(case.fixture),
    )


def _has_forbidden_text_overlap(
    value: str,
    forbidden: frozenset[str],
) -> bool:
    return any(
        len(candidate) >= 8
        and any(
            candidate in blocked or blocked in candidate
            for blocked in forbidden
        )
        for candidate in _decoded_text_variants(value)
    )


def validate_retrieval_routing_gold_isolation(
    suites: LoadedRetrievalRoutingSuites,
    gold_suite: LoadedCaseSuite,
) -> None:
    if (
        not isinstance(suites, LoadedRetrievalRoutingSuites)
        or not isinstance(gold_suite, LoadedCaseSuite)
    ):
        raise ValueError(
            "retrieval routing suite contains Gold contamination"
        )
    forbidden_text = frozenset(
        variant
        for case in gold_suite.cases
        for value in _gold_case_text_values(case)
        if len(value.strip()) >= 8
        for variant in _decoded_text_variants(value)
        if len(variant) >= 8
    )
    forbidden_tables = frozenset(
        _normalized_identifier(table_id).removeprefix(
            "public."
        )
        for case in gold_suite.cases
        for table_id in case.gold_tables
    )
    forbidden_fields = frozenset(
        _normalized_identifier(field_id).removeprefix(
            "public."
        )
        for case in gold_suite.cases
        for field_id in case.gold_fields
    )
    forbidden_joins = frozenset(
        _normalized_join(edge)
        for case in gold_suite.cases
        for edge in case.gold_join_edges
    )
    for suite in (
        suites.development,
        suites.calibration,
    ):
        prefix = f"{suite.namespace}."
        for case in suite.cases:
            domain: str | None = None
            if _has_forbidden_text_overlap(
                case.question,
                forbidden_text,
            ):
                domain = "text"
            elif any(
                _normalized_identifier(
                    table_id.removeprefix(prefix)
                )
                in forbidden_tables
                for table_id in (
                    *case.allowed_tables,
                    *case.expected_tables,
                )
            ):
                domain = "table"
            elif any(
                _normalized_identifier(
                    field_id.removeprefix(prefix)
                )
                in forbidden_fields
                for field_id in case.expected_fields
            ):
                domain = "field"
            elif any(
                _normalized_join(
                    edge.replace(prefix, "")
                )
                in forbidden_joins
                for edge in case.expected_join_edges
            ):
                domain = "join"
            if domain is not None:
                raise ValueError(
                    "retrieval routing suite contains Gold "
                    f"contamination ({case.case_id}:{domain})"
                )


def _validate_full_suite(cases: tuple[EvaluationCase, ...]) -> None:
    expected_ids = tuple(
        f"PG-MVP-{number:03d}" for number in range(1, 19)
    )
    counts = Counter(case.category for case in cases)
    if (
        tuple(case.case_id for case in cases) != expected_ids
        or counts != Counter(_EXPECTED_CATEGORY_COUNTS)
        or len(
            {
                case.case_id
                for case in cases
            }
        )
        != len(cases)
        or len(
            [
                case
                for case in cases
                if case.expected_behavior is ExpectedBehavior.EXECUTE
            ]
        )
        != 15
        or len(
            [
                case
                for case in cases
                if case.expected_behavior is ExpectedBehavior.REJECT
            ]
        )
        != 3
    ):
        raise ValueError("evaluation case suite is invalid")


def load_case_suite(
    path: Path,
    *,
    require_full_suite: bool = True,
) -> LoadedCaseSuite:
    payload, items = _read_lines(path)
    try:
        cases = tuple(
            EvaluationCase.model_validate(item)
            for item in items
        )
    except ValidationError:
        raise ValueError("evaluation case suite is invalid") from None
    if (
        not cases
        or len({case.case_id for case in cases}) != len(cases)
    ):
        raise ValueError("evaluation case suite is invalid")
    if require_full_suite:
        _validate_full_suite(cases)
    return LoadedCaseSuite(
        cases=cases,
        file_sha256=_sha256_bytes(payload),
        status_neutral_sha256=_sha256_bytes(
            _status_neutral_payload(items)
        ),
    )


def _normalize_question(question: str) -> str:
    return " ".join(question.casefold().split())


def _local_expectations(
    suite: LoadedRetrievalRoutingSuite,
) -> set[str]:
    prefix = f"{suite.namespace}."
    local: set[str] = set()
    for case in suite.cases:
        for value in (
            *case.expected_tables,
            *case.expected_fields,
        ):
            local.add(value.removeprefix(prefix))
        for edge in case.expected_join_edges:
            left, right = edge.split("=")
            local.add(
                f"{left.removeprefix(prefix)}="
                f"{right.removeprefix(prefix)}"
            )
    return local


def load_retrieval_routing_suite(
    path: Path,
    *,
    expected_role: RetrievalRoutingSuiteRole,
) -> LoadedRetrievalRoutingSuite:
    try:
        payload, items = _read_lines(path)
        cases = tuple(
            RetrievalRoutingCase.model_validate(item)
            for item in items
        )
    except (ValidationError, ValueError):
        raise ValueError("retrieval routing suite is invalid") from None

    expected_namespace = (
        "synthetic/rrdev"
        if expected_role is RetrievalRoutingSuiteRole.DEVELOPMENT
        else "synthetic/rrcal"
    )
    if (
        len(cases) < 6
        or any(case.suite_role is not expected_role for case in cases)
        or any(case.namespace != expected_namespace for case in cases)
        or len({case.case_id for case in cases}) != len(cases)
        or len({_normalize_question(case.question) for case in cases})
        != len(cases)
        or {case.expected_complexity for case in cases}
        != {
            Difficulty.SIMPLE,
            Difficulty.MEDIUM,
            Difficulty.COMPLEX,
        }
        or {case.expected_top_k for case in cases} != {5, 10, 20}
    ):
        raise ValueError("retrieval routing suite is invalid")

    return LoadedRetrievalRoutingSuite(
        role=expected_role,
        namespace=expected_namespace,
        cases=cases,
        raw_sha256=_sha256_bytes(payload),
        normalized_sha256=_sha256_bytes(_normalized_payload(items)),
    )


def load_retrieval_routing_suites(
    development_path: Path,
    calibration_path: Path,
) -> LoadedRetrievalRoutingSuites:
    development = load_retrieval_routing_suite(
        development_path,
        expected_role=RetrievalRoutingSuiteRole.DEVELOPMENT,
    )
    calibration = load_retrieval_routing_suite(
        calibration_path,
        expected_role=RetrievalRoutingSuiteRole.CALIBRATION,
    )
    development_ids = {case.case_id for case in development.cases}
    calibration_ids = {case.case_id for case in calibration.cases}
    development_questions = {
        _normalize_question(case.question)
        for case in development.cases
    }
    calibration_questions = {
        _normalize_question(case.question)
        for case in calibration.cases
    }
    if (
        not development_ids.isdisjoint(calibration_ids)
        or not development_questions.isdisjoint(calibration_questions)
        or not _local_expectations(development).isdisjoint(
            _local_expectations(calibration)
        )
    ):
        raise ValueError(
            "retrieval routing suites are not independent"
        )
    return LoadedRetrievalRoutingSuites(
        development=development,
        calibration=calibration,
    )
