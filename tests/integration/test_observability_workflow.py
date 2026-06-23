import json
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
from text_to_sql_demo.observability.config import (
    ConsoleLoggingConfig,
    FileLoggingConfig,
    LoggingConfig,
)
from text_to_sql_demo.observability.logging import configure_logging
from text_to_sql_demo.workflow.engine import WorkflowEngine
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import NodeRegistry
from text_to_sql_demo.workflow.state import WorkflowState


class ExplodingWorkflowNode(BaseNode):
    """用于观测异常源位置的假节点。"""

    def run(self, state: WorkflowState) -> NodeResult:
        raise RuntimeError("workflow boom")


def test_workflow_node_failure_log_contains_raise_location(tmp_path: Path) -> None:
    log_file = tmp_path / "workflow.log"
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(path=str(log_file)),
        )
    )
    registry = NodeRegistry()
    registry.register("explode", ExplodingWorkflowNode)
    config = WorkflowConfig(
        workflow=WorkflowSection(name="observability_workflow", start_node="first"),
        dialect=DialectConfig(name="sqlite"),
        database=DatabaseConfig(
            default="demo",
            connections={
                "demo": DatabaseConnectionConfig(driver="sqlite", fallback_url="sqlite:///demo.db")
            },
        ),
        nodes={"first": NodeConfig(type="explode")},
        edges={"first": EdgeConfig(terminal=True)},
    )

    state = WorkflowEngine(
        config=config,
        node_factory=NodeFactory(registry=registry),
    ).run(WorkflowState(request_id="req-workflow", user_question="boom"))

    assert state.termination_reason == "node_error"
    failed_event = _event_by_name(log_file, "workflow.node.failed")
    assert failed_event["request_id"] == "req-workflow"
    assert failed_event["workflow_name"] == "observability_workflow"
    assert failed_event["node_name"] == "first"
    assert failed_event["error_type"] == "RuntimeError"
    assert failed_event["error_file"].endswith("test_observability_workflow.py")
    assert failed_event["error_function"] == "run"
    assert isinstance(failed_event["error_line"], int)


def _event_by_name(log_file: Path, event_name: str) -> dict:
    for line in log_file.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if payload.get("event") == event_name:
            return payload
    raise AssertionError(f"missing log event: {event_name}")

