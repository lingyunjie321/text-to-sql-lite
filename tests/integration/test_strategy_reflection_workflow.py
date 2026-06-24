from text_to_sql_demo.config.models import (
    DatabaseConfig,
    DatabaseConnectionConfig,
    EdgeConfig,
    NodeConfig,
    WorkflowConfig,
    WorkflowSection,
)
from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.nodes.error_reflection import ReflectionDecisionNode
from text_to_sql_demo.nodes.finalization import FinalizeNode
from text_to_sql_demo.nodes.reasoning_rewrite import ReasoningRewriteNode
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.engine import WorkflowEngine
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import NodeRegistry
from text_to_sql_demo.workflow.state import WorkflowState


class UnknownTableValidationNode(BaseNode):
    """测试用节点：稳定产生 unknown_table 校验失败。"""

    def run(self, state: WorkflowState) -> NodeResult:
        error = {
            "category": "unknown_table",
            "message": "表不存在: missing_orders",
            "table": "missing_orders",
        }
        return NodeResult(
            outcome="validation_failed",
            state_patch={
                "data": {
                    "current_sql": "SELECT * FROM missing_orders",
                    "last_error": error,
                    "validation_result": {"success": False, "error": error},
                }
            },
        )


class SchemaLinkingMarkerNode(BaseNode):
    """测试用节点：标记 workflow 已路由回 schema_linking。"""

    def run(self, state: WorkflowState) -> NodeResult:
        return NodeResult(
            outcome="success",
            state_patch={"data": {"routed_to_schema_linking": True}},
        )


class ExecutionFailureNode(BaseNode):
    """测试用节点：稳定产生 execution_error。"""

    def run(self, state: WorkflowState) -> NodeResult:
        error = {
            "category": "execution_error",
            "message": "no such function: bad_metric",
        }
        return NodeResult(
            outcome="execution_failed",
            state_patch={
                "data": {
                    "current_sql": "SELECT bad_metric(amount) FROM orders",
                    "last_error": error,
                    "execution_result": {"success": False, "error": error},
                }
            },
        )


class ValidationPassNode(BaseNode):
    """测试用节点：验证 reasoning rewrite 后确实回到校验阶段。"""

    def run(self, state: WorkflowState) -> NodeResult:
        sql = str(state.data["current_sql"])
        return NodeResult(
            outcome="validation_success",
            state_patch={
                "data": {
                    "validated_sql": sql,
                    "validation_after_rewrite": True,
                    "validation_result": {"success": True, "normalized_sql": sql},
                }
            },
        )


def test_unknown_table_strategy_routes_back_to_schema_linking() -> None:
    registry = NodeRegistry()
    registry.register("unknown_table_validation", UnknownTableValidationNode)
    registry.register("reflection_decision", ReflectionDecisionNode)
    registry.register("schema_linking_marker", SchemaLinkingMarkerNode)
    registry.register("finalization", FinalizeNode)
    config = WorkflowConfig(
        workflow=WorkflowSection(
            name="unknown_table_strategy",
            start_node="validate",
            max_steps=10,
            max_repair_attempts=3,
        ),
        database=DatabaseConfig(
            default="demo",
            connections={"demo": DatabaseConnectionConfig(driver="sqlite")},
        ),
        nodes={
            "validate": NodeConfig(type="unknown_table_validation"),
            "reflect": NodeConfig(type="reflection_decision", max_repair_attempts=3),
            "schema_linking": NodeConfig(type="schema_linking_marker"),
            "finalize": NodeConfig(type="finalization"),
        },
        edges={
            "validate": EdgeConfig(on_validation_failed="reflect"),
            "reflect": EdgeConfig(on_relink_schema="schema_linking"),
            "schema_linking": EdgeConfig(on_success="finalize"),
            "finalize": EdgeConfig(terminal=True),
        },
    )

    result = WorkflowEngine(
        config=config,
        node_factory=NodeFactory(registry=registry),
    ).run(WorkflowState(user_question="查询缺失订单表"))

    assert result.data["reflection_decision"]["strategy"] == "RELINK_SCHEMA"
    assert result.data["attempt_count"] == 1
    assert result.data["routed_to_schema_linking"] is True
    assert [event.node_name for event in result.trace[:3]] == [
        "validate",
        "reflect",
        "schema_linking",
    ]


def test_execution_error_strategy_rewrites_then_returns_to_validation() -> None:
    registry = NodeRegistry()
    registry.register("execution_failure", ExecutionFailureNode)
    registry.register("reflection_decision", ReflectionDecisionNode)
    registry.register("reasoning_rewrite", ReasoningRewriteNode)
    registry.register("validation_pass", ValidationPassNode)
    registry.register("finalization", FinalizeNode)
    config = WorkflowConfig(
        workflow=WorkflowSection(
            name="execution_error_strategy",
            start_node="execute",
            max_steps=10,
            max_repair_attempts=3,
        ),
        database=DatabaseConfig(
            default="demo",
            connections={"demo": DatabaseConnectionConfig(driver="sqlite")},
        ),
        nodes={
            "execute": NodeConfig(type="execution_failure"),
            "reflect": NodeConfig(type="reflection_decision", max_repair_attempts=3),
            "rewrite": NodeConfig(type="reasoning_rewrite", model_alias="strong"),
            "validate": NodeConfig(type="validation_pass"),
            "finalize": NodeConfig(type="finalization"),
        },
        edges={
            "execute": EdgeConfig(on_execution_failed="reflect"),
            "reflect": EdgeConfig(on_reasoning_rewrite="rewrite"),
            "rewrite": EdgeConfig(on_rewrite_complete="validate"),
            "validate": EdgeConfig(on_validation_success="finalize"),
            "finalize": EdgeConfig(terminal=True),
        },
    )
    dependencies = NodeDependencies(
        values={
            "llm_client": MockLLMClient(responses={"strong": "SELECT SUM(amount) FROM orders"}),
            "model_profiles": {
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model")
            },
        }
    )

    result = WorkflowEngine(
        config=config,
        node_factory=NodeFactory(registry=registry, dependencies=dependencies),
    ).run(
        WorkflowState(
            user_question="统计订单金额",
            data={
                "schema_linking": {
                    "tables": [
                        {
                            "name": "orders",
                            "columns": {"amount": {"name": "amount", "type": "NUMERIC"}},
                        }
                    ]
                }
            },
        )
    )

    assert result.data["reflection_decision"]["strategy"] == "REASONING_REWRITE"
    assert result.data["attempt_count"] == 1
    assert result.data["generated_sql"] == "SELECT SUM(amount) FROM orders"
    assert result.data["validation_after_rewrite"] is True
    assert [event.node_name for event in result.trace[:4]] == [
        "execute",
        "reflect",
        "rewrite",
        "validate",
    ]
