from pathlib import Path

from text_to_sql_demo.config.models import (
    DatabaseConfig,
    DatabaseConnectionConfig,
    DialectConfig,
    EdgeConfig,
    NodeConfig,
    WorkflowConfig,
    WorkflowSection,
)
from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.nodes.error_reflection import ReflectErrorNode
from text_to_sql_demo.nodes.finalization import FinalizeNode
from text_to_sql_demo.nodes.sql_execution import ExecuteSQLNode
from text_to_sql_demo.nodes.sql_fix import FixSQLNode
from text_to_sql_demo.nodes.sql_validation import ValidateSQLNode
from text_to_sql_demo.schema.catalog import read_schema_metadata
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.engine import WorkflowEngine
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.registry import NodeRegistry
from text_to_sql_demo.workflow.state import WorkflowState


def build_workflow_config(*, max_repair_attempts: int = 3) -> WorkflowConfig:
    return WorkflowConfig(
        workflow=WorkflowSection(
            name="sql_repair_loop",
            start_node="validate",
            max_steps=30,
            max_repair_attempts=max_repair_attempts,
        ),
        dialect=DialectConfig(name="sqlite"),
        database=DatabaseConfig(
            default="demo",
            connections={
                "demo": DatabaseConnectionConfig(
                    driver="sqlite",
                    fallback_url="sqlite:///demo.db",
                )
            },
        ),
        nodes={
            "validate": NodeConfig(type="sql_validation", target_dialect="sqlite"),
            "execute": NodeConfig(type="sql_execution", max_rows=10),
            "reflect": NodeConfig(
                type="error_reflection",
                max_repair_attempts=max_repair_attempts,
            ),
            "fix": NodeConfig(type="sql_fix", model_alias="strong"),
            "finalize": NodeConfig(type="finalization"),
        },
        edges={
            "validate": EdgeConfig(
                on_validation_success="execute",
                on_validation_failed="reflect",
            ),
            "execute": EdgeConfig(
                on_execution_success="finalize",
                on_execution_failed="reflect",
            ),
            "reflect": EdgeConfig(
                on_reflect_retry="fix",
                on_attempts_exhausted="finalize",
            ),
            "fix": EdgeConfig(on_fix_complete="validate"),
            "finalize": EdgeConfig(terminal=True),
        },
    )


def build_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register("sql_validation", ValidateSQLNode)
    registry.register("sql_execution", ExecuteSQLNode)
    registry.register("error_reflection", ReflectErrorNode)
    registry.register("sql_fix", FixSQLNode)
    registry.register("finalization", FinalizeNode)
    return registry


def build_state(tmp_path: Path, generated_sql: str) -> tuple[WorkflowState, str]:
    db_path = tmp_path / "demo.db"
    initialize_database(db_path)
    database_url = f"sqlite:///{db_path}"
    schema = read_schema_metadata(database_url)
    return (
        WorkflowState(
            user_question="统计订单金额",
            data={
                "generated_sql": generated_sql,
                "schema": schema.model_dump(mode="python"),
                "target_dialect": "sqlite",
            },
        ),
        database_url,
    )


def run_workflow(
    *,
    state: WorkflowState,
    database_url: str,
    llm_client: MockLLMClient | None = None,
    max_repair_attempts: int = 3,
) -> WorkflowState:
    dependencies = NodeDependencies(
        values={
            "database_url": database_url,
            "llm_client": llm_client or MockLLMClient(),
            "model_profiles": {
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
                "light": ModelProfile(alias="light", provider="mock", model_name="light-model"),
            },
        }
    )
    engine = WorkflowEngine(
        config=build_workflow_config(max_repair_attempts=max_repair_attempts),
        node_factory=NodeFactory(registry=build_registry(), dependencies=dependencies),
    )
    return engine.run(state)


def test_correct_sql_executes_successfully_on_first_pass(tmp_path: Path) -> None:
    state, database_url = build_state(
        tmp_path,
        "SELECT id, amount FROM orders ORDER BY id",
    )

    result = run_workflow(state=state, database_url=database_url)

    assert result.data["final_status"] == "success"
    assert result.data["execution_result"]["columns"] == ["id", "amount"]
    assert result.data["attempt_count"] == 0
    assert [event.node_name for event in result.trace] == ["validate", "execute", "finalize"]


def test_unknown_column_is_reflected_fixed_and_then_executes(tmp_path: Path) -> None:
    state, database_url = build_state(
        tmp_path,
        "SELECT SUM(orders.total_amount) AS total FROM orders",
    )
    llm_client = MockLLMClient(
        responses={"strong": "SELECT SUM(orders.amount) AS total FROM orders"}
    )

    result = run_workflow(state=state, database_url=database_url, llm_client=llm_client)

    assert result.data["final_status"] == "success"
    assert result.data["attempt_count"] == 1
    assert result.data["repair_history"][0]["error_type"] == "unknown_column"
    assert result.data["repair_history"][0]["old_sql"] == (
        "SELECT SUM(orders.total_amount) AS total FROM orders"
    )
    assert result.data["repair_history"][0]["new_sql"] == (
        "SELECT SUM(orders.amount) AS total FROM orders"
    )
    assert result.data["repair_history"][0]["strategy_name"] == "repair_unknown_column"
    assert [event.node_name for event in result.trace] == [
        "validate",
        "reflect",
        "fix",
        "validate",
        "execute",
        "finalize",
    ]


def test_unknown_table_is_classified(tmp_path: Path) -> None:
    state, database_url = build_state(tmp_path, "SELECT * FROM missing_orders")

    result = run_workflow(
        state=state,
        database_url=database_url,
        max_repair_attempts=0,
    )

    assert result.data["final_status"] == "failed"
    assert result.data["last_error"]["category"] == "unknown_table"
    assert result.data["validation_result"]["error"]["category"] == "unknown_table"


def test_repair_loop_terminates_after_three_failed_attempts(tmp_path: Path) -> None:
    state, database_url = build_state(
        tmp_path,
        "SELECT SUM(orders.total_amount) AS total FROM orders",
    )
    llm_client = MockLLMClient(
        responses={"strong": "SELECT SUM(orders.total_amount) AS total FROM orders"}
    )

    result = run_workflow(state=state, database_url=database_url, llm_client=llm_client)

    assert result.data["final_status"] == "failed"
    assert result.data["attempt_count"] == 3
    assert result.data["termination_reason"] == "attempts_exhausted"
    assert len(result.data["repair_history"]) == 3
    assert result.trace[-2].outcome == "attempts_exhausted"
    assert result.trace[-1].node_name == "finalize"


def test_every_round_produces_complete_trace(tmp_path: Path) -> None:
    state, database_url = build_state(
        tmp_path,
        "SELECT SUM(orders.total_amount) AS total FROM orders",
    )
    llm_client = MockLLMClient(
        responses={"strong": "SELECT SUM(orders.total_amount) AS total FROM orders"}
    )

    result = run_workflow(state=state, database_url=database_url, llm_client=llm_client)

    assert len(result.trace) == 12
    for event in result.trace:
        assert event.node_name
        assert event.node_type
        assert event.status == "success"
        assert event.outcome
        assert event.duration_ms >= 0
