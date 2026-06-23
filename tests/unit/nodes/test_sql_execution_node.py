from text_to_sql_demo.execution.sql_executor import SQLExecutor
from text_to_sql_demo.nodes.sql_execution import ExecuteSQLNode
from text_to_sql_demo.sql.models import SQLExecutionResult
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.state import WorkflowState


def test_execute_node_allows_postgres_when_validated_dialect_matches(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_execute(
        self: SQLExecutor,
        *,
        sql: str,
        database_url: str,
        max_rows: int,
    ) -> SQLExecutionResult:
        captured.update({"sql": sql, "database_url": database_url, "max_rows": max_rows})
        return SQLExecutionResult(success=True, columns=["id"], rows=[{"id": 1}])

    monkeypatch.setattr(SQLExecutor, "execute", fake_execute)
    node = ExecuteSQLNode(
        name="execute",
        config={"execution_dialect": "postgres", "max_rows": 5},
        dependencies=NodeDependencies(
            values={
                "database_url": "postgresql+psycopg://readonly:secret@db.example.com:5432/app"
            }
        ),
    )
    state = WorkflowState(
        user_question="列出订单",
        data={
            "validated_sql": "SELECT id FROM orders",
            "validated_sql_dialect": "postgres",
        },
    )

    result = node.run(state)

    assert result.outcome == "execution_success"
    assert captured == {
        "sql": "SELECT id FROM orders",
        "database_url": "postgresql+psycopg://readonly:secret@db.example.com:5432/app",
        "max_rows": 5,
    }
