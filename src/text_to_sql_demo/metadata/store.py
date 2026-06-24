from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from text_to_sql_demo.exceptions import MetadataStoreError
from text_to_sql_demo.metadata.models import (
    FeedbackList,
    FeedbackRecord,
    QueryRunList,
    QueryRunRecord,
    SavedQueryList,
    SavedQueryRecord,
    SavedQueryStatus,
    StoredQueryRun,
    TraceEventRecord,
)

DEFAULT_METADATA_DATABASE_URL = "sqlite:///data/sqlite/metadata.db"


class MetadataStore:
    """项目内部 metadata store，保存运行记录、Trace、收藏 SQL 和反馈。"""

    def __init__(self, *, database_url: str = DEFAULT_METADATA_DATABASE_URL) -> None:
        self.database_url = database_url
        _ensure_sqlite_parent(database_url)
        self._metadata = MetaData()
        self.query_runs = _query_runs_table(self._metadata)
        self.trace_events = _trace_events_table(self._metadata)
        self.saved_queries = _saved_queries_table(self._metadata)
        self.feedback = _feedback_table(self._metadata)
        self._engine = create_engine(database_url)
        self._ensure_schema()

    def save_query_run(
        self,
        run: QueryRunRecord,
        *,
        trace_events: list[TraceEventRecord] | None = None,
    ) -> QueryRunRecord:
        """幂等保存一次运行记录，并用最新 Trace 覆盖旧 Trace。"""
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    delete(self.query_runs).where(
                        self.query_runs.c.request_id == run.request_id
                    )
                )
                connection.execute(insert(self.query_runs).values(_query_run_to_row(run)))
                connection.execute(
                    delete(self.trace_events).where(
                        self.trace_events.c.request_id == run.request_id
                    )
                )
                for event in trace_events or []:
                    connection.execute(
                        insert(self.trace_events).values(_trace_event_to_row(event))
                    )
            return run
        except SQLAlchemyError as exc:
            raise MetadataStoreError("保存查询运行记录失败") from exc

    def get_query_run(self, request_id: str) -> StoredQueryRun | None:
        """按 request_id 读取运行记录和 Trace。"""
        try:
            with self._engine.connect() as connection:
                run_row = connection.execute(
                    select(self.query_runs).where(self.query_runs.c.request_id == request_id)
                ).mappings().first()
                if run_row is None:
                    return None
                trace_rows = connection.execute(
                    select(self.trace_events)
                    .where(self.trace_events.c.request_id == request_id)
                    .order_by(self.trace_events.c.step.asc())
                ).mappings().all()
            return StoredQueryRun(
                query_run=_row_to_query_run(run_row),
                trace_events=[_row_to_trace_event(row) for row in trace_rows],
            )
        except SQLAlchemyError as exc:
            raise MetadataStoreError("读取查询运行记录失败") from exc

    def list_query_runs(self, *, limit: int = 20) -> QueryRunList:
        """按更新时间倒序列出运行记录。"""
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(
                    select(self.query_runs)
                    .order_by(self.query_runs.c.updated_at.desc())
                    .limit(limit)
                ).mappings().all()
                total = connection.execute(
                    select(func.count()).select_from(self.query_runs)
                ).scalar_one()
            return QueryRunList(
                items=[_row_to_query_run(row) for row in rows],
                total=int(total),
            )
        except SQLAlchemyError as exc:
            raise MetadataStoreError("列出查询运行记录失败") from exc

    def save_saved_query(self, saved_query: SavedQueryRecord) -> SavedQueryRecord:
        """保存或覆盖一条收藏 SQL。"""
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    delete(self.saved_queries).where(
                        self.saved_queries.c.id == saved_query.id
                    )
                )
                connection.execute(
                    insert(self.saved_queries).values(_saved_query_to_row(saved_query))
                )
            return saved_query
        except SQLAlchemyError as exc:
            raise MetadataStoreError("保存收藏 SQL 失败") from exc

    def list_saved_queries(
        self,
        *,
        status: SavedQueryStatus | None = None,
        limit: int = 20,
    ) -> SavedQueryList:
        """按更新时间倒序列出收藏 SQL。"""
        try:
            statement = (
                select(self.saved_queries)
                .order_by(self.saved_queries.c.updated_at.desc())
                .limit(limit)
            )
            count_statement = select(func.count()).select_from(self.saved_queries)
            if status is not None:
                statement = statement.where(self.saved_queries.c.status == status)
                count_statement = count_statement.where(self.saved_queries.c.status == status)
            with self._engine.connect() as connection:
                rows = connection.execute(statement).mappings().all()
                total = connection.execute(count_statement).scalar_one()
            return SavedQueryList(
                items=[_row_to_saved_query(row) for row in rows],
                total=int(total),
            )
        except SQLAlchemyError as exc:
            raise MetadataStoreError("列出收藏 SQL 失败") from exc

    def update_saved_query_status(
        self,
        saved_query_id: str,
        *,
        status: SavedQueryStatus,
        updated_at: datetime,
    ) -> SavedQueryRecord | None:
        """更新收藏 SQL 的轻量审核状态，不处理权限和多租户。"""
        try:
            with self._engine.begin() as connection:
                existing = connection.execute(
                    select(self.saved_queries).where(
                        self.saved_queries.c.id == saved_query_id
                    )
                ).mappings().first()
                if existing is None:
                    return None
                connection.execute(
                    update(self.saved_queries)
                    .where(self.saved_queries.c.id == saved_query_id)
                    .values(status=status, updated_at=updated_at.isoformat())
                )
                row = connection.execute(
                    select(self.saved_queries).where(
                        self.saved_queries.c.id == saved_query_id
                    )
                ).mappings().one()
            return _row_to_saved_query(row)
        except SQLAlchemyError as exc:
            raise MetadataStoreError("更新收藏 SQL 状态失败") from exc

    def save_feedback(self, feedback: FeedbackRecord) -> FeedbackRecord:
        """保存用户对某次运行的反馈。"""
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    delete(self.feedback).where(self.feedback.c.id == feedback.id)
                )
                connection.execute(insert(self.feedback).values(_feedback_to_row(feedback)))
            return feedback
        except SQLAlchemyError as exc:
            raise MetadataStoreError("保存用户反馈失败") from exc

    def list_feedback(self, *, request_id: str | None = None, limit: int = 20) -> FeedbackList:
        """列出反馈，可按 request_id 过滤。"""
        try:
            statement = (
                select(self.feedback)
                .order_by(self.feedback.c.created_at.desc())
                .limit(limit)
            )
            count_statement = select(func.count()).select_from(self.feedback)
            if request_id is not None:
                statement = statement.where(self.feedback.c.request_id == request_id)
                count_statement = count_statement.where(self.feedback.c.request_id == request_id)
            with self._engine.connect() as connection:
                rows = connection.execute(statement).mappings().all()
                total = connection.execute(count_statement).scalar_one()
            return FeedbackList(
                items=[_row_to_feedback(row) for row in rows],
                total=int(total),
            )
        except SQLAlchemyError as exc:
            raise MetadataStoreError("列出用户反馈失败") from exc

    def dispose(self) -> None:
        """释放 SQLAlchemy engine 资源。"""
        self._engine.dispose()

    @property
    def engine(self) -> Engine:
        """暴露只读 engine 引用，便于测试或诊断。"""
        return self._engine

    def _ensure_schema(self) -> None:
        self._metadata.create_all(self._engine)
        self._ensure_query_run_response_column()

    def _ensure_query_run_response_column(self) -> None:
        """兼容上一版 metadata.db，补齐历史详情响应字段。"""
        inspector = inspect(self._engine)
        column_names = {
            column["name"]
            for column in inspector.get_columns(self.query_runs.name)
        }
        if "response_json" in column_names:
            return
        with self._engine.begin() as connection:
            connection.execute(text("ALTER TABLE query_run ADD COLUMN response_json TEXT"))


def _query_runs_table(metadata: MetaData) -> Table:
    return Table(
        "query_run",
        metadata,
        Column("request_id", String(80), primary_key=True),
        Column("question", Text, nullable=False),
        Column("status", String(40), nullable=False),
        Column("final_sql", Text),
        Column("attempts", Integer, nullable=False, default=0),
        Column("selected_model", String(120)),
        Column("routing_reason", Text),
        Column("target_dialect", String(40), nullable=False),
        Column("runtime_config_id", String(120)),
        Column("row_count", Integer),
        Column("error_message", Text),
        Column("response_json", Text),
        Column("created_at", String(40), nullable=False),
        Column("updated_at", String(40), nullable=False),
    )


def _trace_events_table(metadata: MetaData) -> Table:
    return Table(
        "trace_event",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("request_id", String(80), nullable=False, index=True),
        Column("step", Integer, nullable=False),
        Column("node_name", String(160), nullable=False),
        Column("node_type", String(160), nullable=False),
        Column("status", String(40), nullable=False),
        Column("outcome", String(80), nullable=False),
        Column("duration_ms", Integer, nullable=False),
        Column("input_summary_json", Text, nullable=False),
        Column("output_summary_json", Text, nullable=False),
        Column("error_json", Text),
        Column("started_at", String(40), nullable=False),
        Column("ended_at", String(40), nullable=False),
    )


def _saved_queries_table(metadata: MetaData) -> Table:
    return Table(
        "saved_query",
        metadata,
        Column("id", String(80), primary_key=True),
        Column("name", String(200), nullable=False),
        Column("question", Text, nullable=False),
        Column("sql", Text, nullable=False),
        Column("created_from_run_id", String(80)),
        Column("tags_json", Text, nullable=False),
        Column("status", String(40), nullable=False),
        Column("created_at", String(40), nullable=False),
        Column("updated_at", String(40), nullable=False),
    )


def _feedback_table(metadata: MetaData) -> Table:
    return Table(
        "feedback",
        metadata,
        Column("id", String(80), primary_key=True),
        Column("request_id", String(80), nullable=False, index=True),
        Column("rating", String(20), nullable=False),
        Column("issue_type", String(80)),
        Column("comment", Text),
        Column("created_at", String(40), nullable=False),
    )


def _query_run_to_row(run: QueryRunRecord) -> dict[str, Any]:
    payload = run.model_dump(mode="python")
    payload["response_json"] = (
        _dump_json(run.response_payload) if run.response_payload is not None else None
    )
    del payload["response_payload"]
    payload["created_at"] = run.created_at.isoformat()
    payload["updated_at"] = run.updated_at.isoformat()
    return payload


def _trace_event_to_row(event: TraceEventRecord) -> dict[str, Any]:
    payload = event.model_dump(mode="python")
    return {
        **{
            key: value
            for key, value in payload.items()
            if key not in {"input_summary", "output_summary", "error"}
        },
        "input_summary_json": _dump_json(event.input_summary),
        "output_summary_json": _dump_json(event.output_summary),
        "error_json": _dump_json(event.error) if event.error is not None else None,
        "started_at": event.started_at.isoformat(),
        "ended_at": event.ended_at.isoformat(),
    }


def _saved_query_to_row(saved_query: SavedQueryRecord) -> dict[str, Any]:
    payload = saved_query.model_dump(mode="python")
    payload["tags_json"] = _dump_json(saved_query.tags)
    payload["created_at"] = saved_query.created_at.isoformat()
    payload["updated_at"] = saved_query.updated_at.isoformat()
    del payload["tags"]
    return payload


def _feedback_to_row(feedback: FeedbackRecord) -> dict[str, Any]:
    payload = feedback.model_dump(mode="python")
    payload["created_at"] = feedback.created_at.isoformat()
    return payload


def _row_to_query_run(row: Any) -> QueryRunRecord:
    payload = dict(row)
    payload["response_payload"] = _load_json(payload.pop("response_json", None), default=None)
    payload["created_at"] = _parse_datetime(payload["created_at"])
    payload["updated_at"] = _parse_datetime(payload["updated_at"])
    return QueryRunRecord.model_validate(payload)


def _row_to_trace_event(row: Any) -> TraceEventRecord:
    payload = dict(row)
    payload.pop("id", None)
    payload["input_summary"] = _load_json(payload.pop("input_summary_json"), default={})
    payload["output_summary"] = _load_json(payload.pop("output_summary_json"), default={})
    payload["error"] = _load_json(payload.pop("error_json"), default=None)
    payload["started_at"] = _parse_datetime(payload["started_at"])
    payload["ended_at"] = _parse_datetime(payload["ended_at"])
    return TraceEventRecord.model_validate(payload)


def _row_to_saved_query(row: Any) -> SavedQueryRecord:
    payload = dict(row)
    payload["tags"] = _load_json(payload.pop("tags_json"), default=[])
    payload["created_at"] = _parse_datetime(payload["created_at"])
    payload["updated_at"] = _parse_datetime(payload["updated_at"])
    return SavedQueryRecord.model_validate(payload)


def _row_to_feedback(row: Any) -> FeedbackRecord:
    payload = dict(row)
    payload["created_at"] = _parse_datetime(payload["created_at"])
    return FeedbackRecord.model_validate(payload)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str | None, *, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in {None, "", ":memory:"}:
        return
    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
