from text_to_sql_demo.exceptions import NodeExecutionError
from text_to_sql_demo.execution.sql_executor import SQLExecutor
from text_to_sql_demo.observability.events import log_sql_execution_failed
from text_to_sql_demo.sql.models import SQLError, SQLExecutionResult
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState

SUPPORTED_EXECUTION_DIALECTS = {"sqlite", "postgres", "mysql"}


@register_node("sql_execution")
class ExecuteSQLNode(BaseNode):
    """执行已校验 SQL 并返回结构化结果。"""

    def run(self, state: WorkflowState) -> NodeResult:
        sql = str(state.data.get("validated_sql") or state.data.get("current_sql") or "")
        database_url = self.dependencies.get("database_url") or self.config.get("database_url")
        if not database_url:
            raise NodeExecutionError("ExecuteSQLNode requires database_url dependency or config")

        execution_dialect = str(self.config.get("execution_dialect", "sqlite"))
        validated_sql_dialect = str(state.data.get("validated_sql_dialect") or execution_dialect)
        if (
            execution_dialect not in SUPPORTED_EXECUTION_DIALECTS
            or validated_sql_dialect != execution_dialect
        ):
            error = SQLError(
                category="dialect_error",
                message="执行方言必须受支持，并且与已校验 SQL 方言一致",
                raw_message=(
                    f"execution_dialect={execution_dialect}, "
                    f"validated_sql_dialect={validated_sql_dialect}"
                ),
            )
            payload = SQLExecutionResult(success=False, error=error).model_dump(mode="python")
            log_sql_execution_failed(
                request_id=state.request_id,
                node_name=self.name,
                error_category=error.category,
                sql=sql,
            )
            return NodeResult(
                outcome="execution_failed",
                state_patch={
                    "data": {
                        "execution_result": payload,
                        "last_error": error.model_dump(mode="python"),
                        "current_sql": sql,
                    }
                },
                output={"execution_result": payload},
            )

        result = SQLExecutor().execute(
            sql=sql,
            database_url=str(database_url),
            max_rows=int(self.config.get("max_rows", 100)),
        )
        payload = result.model_dump(mode="python")
        if result.success:
            return NodeResult(
                outcome="execution_success",
                state_patch={"data": {"execution_result": payload}},
                output={"execution_result": payload},
            )

        error_payload = result.error.model_dump(mode="python") if result.error else None
        log_sql_execution_failed(
            request_id=state.request_id,
            node_name=self.name,
            error_category=result.error.category if result.error else None,
            sql=sql,
        )
        return NodeResult(
            outcome="execution_failed",
            state_patch={
                "data": {
                    "execution_result": payload,
                    "last_error": error_payload,
                    "current_sql": sql,
                }
            },
            output={"execution_result": payload},
        )
