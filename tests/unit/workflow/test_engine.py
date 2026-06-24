from __future__ import annotations

import json
from typing import ClassVar

import pytest

from text_to_sql_demo.config.models import (
    DatabaseConfig,
    DatabaseConnectionConfig,
    DialectConfig,
    EdgeConfig,
    NodeConfig,
    WorkflowConfig,
    WorkflowSection,
)
from text_to_sql_demo.workflow.engine import WorkflowEngine
from text_to_sql_demo.workflow.exceptions import NodeRegistrationError
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import NodeRegistry, register_node
from text_to_sql_demo.workflow.state import WorkflowState


class AppendNode(BaseNode):
    """记录自身名称到 state.data 的假节点。"""

    def run(self, state: WorkflowState) -> NodeResult:
        visited = [*state.data.get("visited", []), self.name]
        return NodeResult(
            outcome=str(self.config.get("outcome", "success")),
            state_patch={"data": {"visited": visited}},
        )


class ExplodingNode(BaseNode):
    """用于 Trace 测试的异常假节点。"""

    def run(self, state: WorkflowState) -> NodeResult:
        raise RuntimeError("boom")


class HookNode(BaseNode):
    """记录生命周期钩子调用的假节点。"""

    events: ClassVar[list[str]] = []

    def before(self, state: WorkflowState) -> None:
        self.events.append(f"before:{self.name}")

    def run(self, state: WorkflowState) -> NodeResult:
        self.events.append(f"run:{self.name}")
        return NodeResult(outcome="success", state_patch={"data": {"hooked": True}})

    def after(self, state: WorkflowState, result: NodeResult) -> None:
        self.events.append(f"after:{self.name}:{result.outcome}")

    def error(self, state: WorkflowState, error: Exception) -> None:
        self.events.append(f"error:{self.name}:{error}")


class HookExplodingNode(HookNode):
    """在 before 钩子后抛出异常的假节点。"""

    def run(self, state: WorkflowState) -> NodeResult:
        self.events.append(f"run:{self.name}")
        raise RuntimeError("hook boom")


class SqlSummaryNode(BaseNode):
    """返回包含 SQL 的结果，用于验证 Trace 默认不泄露 SQL 文本。"""

    def run(self, state: WorkflowState) -> NodeResult:
        sql = "SELECT id, amount FROM orders"
        return NodeResult(
            outcome="success",
            output={"generated_sql": sql},
            state_patch={"data": {"current_sql": sql}},
        )


def make_config(
    *,
    nodes: dict[str, NodeConfig],
    edges: dict[str, EdgeConfig],
    start_node: str = "first",
    max_steps: int = 10,
) -> WorkflowConfig:
    return WorkflowConfig(
        workflow=WorkflowSection(
            name="fake_workflow",
            start_node=start_node,
            max_steps=max_steps,
            max_repair_attempts=3,
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
        nodes=nodes,
        edges=edges,
    )


def make_engine(registry: NodeRegistry, config: WorkflowConfig) -> WorkflowEngine:
    return WorkflowEngine(config=config, node_factory=NodeFactory(registry=registry))


def test_three_fake_nodes_execute_in_configured_order() -> None:
    registry = NodeRegistry()
    registry.register("append", AppendNode)
    config = make_config(
        nodes={
            "first": NodeConfig(type="append"),
            "second": NodeConfig(type="append"),
            "third": NodeConfig(type="append"),
        },
        edges={
            "first": EdgeConfig(on_success="second"),
            "second": EdgeConfig(on_success="third"),
            "third": EdgeConfig(terminal=True),
        },
    )

    state = make_engine(registry, config).run(WorkflowState(user_question="demo"))

    assert state.data["visited"] == ["first", "second", "third"]
    assert state.terminated is True
    assert [event.node_name for event in state.trace] == ["first", "second", "third"]


def test_outcome_selects_configured_branch() -> None:
    registry = NodeRegistry()
    registry.register("append", AppendNode)
    config = make_config(
        nodes={
            "first": NodeConfig(type="append", outcome="vip"),
            "vip_path": NodeConfig(type="append"),
            "regular_path": NodeConfig(type="append"),
        },
        edges={
            "first": EdgeConfig(on_vip="vip_path", on_regular="regular_path"),
            "vip_path": EdgeConfig(terminal=True),
            "regular_path": EdgeConfig(terminal=True),
        },
    )

    state = make_engine(registry, config).run(WorkflowState(user_question="branch"))

    assert state.data["visited"] == ["first", "vip_path"]
    assert [event.outcome for event in state.trace] == ["vip", "success"]


def test_unregistered_node_type_returns_clear_error() -> None:
    registry = NodeRegistry()
    config = make_config(
        nodes={"first": NodeConfig(type="missing")},
        edges={"first": EdgeConfig(terminal=True)},
    )

    with pytest.raises(NodeRegistrationError, match="节点类型未注册: missing"):
        make_engine(registry, config).run(WorkflowState(user_question="missing"))


def test_node_exception_records_trace_and_terminates() -> None:
    registry = NodeRegistry()
    registry.register("explode", ExplodingNode)
    config = make_config(
        nodes={"first": NodeConfig(type="explode")},
        edges={"first": EdgeConfig(terminal=True)},
    )

    state = make_engine(registry, config).run(WorkflowState(user_question="explode"))

    assert state.terminated is True
    assert state.termination_reason == "node_error"
    assert state.errors[0].message == "boom"
    assert state.trace[0].status == "error"
    assert state.trace[0].error_message == "boom"


def test_loop_terminates_when_max_steps_is_exceeded() -> None:
    registry = NodeRegistry()
    registry.register("append", AppendNode)
    config = make_config(
        nodes={"first": NodeConfig(type="append")},
        edges={"first": EdgeConfig(on_success="first")},
        max_steps=2,
    )

    state = make_engine(registry, config).run(WorkflowState(user_question="loop"))

    assert state.terminated is True
    assert state.termination_reason == "max_steps_exceeded"
    assert state.step_count == 2
    assert state.data["visited"] == ["first", "first"]


def test_registering_new_fake_node_does_not_require_engine_changes() -> None:
    registry = NodeRegistry()

    @register_node("decorated_append", registry=registry)
    class DecoratedAppendNode(AppendNode):
        pass

    config = make_config(
        nodes={"first": NodeConfig(type="decorated_append")},
        edges={"first": EdgeConfig(terminal=True)},
    )

    state = make_engine(registry, config).run(WorkflowState(user_question="decorator"))

    assert state.data["visited"] == ["first"]
    assert registry.get("decorated_append") is DecoratedAppendNode


def test_lifecycle_hooks_are_called_for_success_and_error() -> None:
    HookNode.events = []
    registry = NodeRegistry()
    registry.register("hook", HookNode)
    registry.register("hook_explode", HookExplodingNode)

    success_config = make_config(
        nodes={"first": NodeConfig(type="hook")},
        edges={"first": EdgeConfig(terminal=True)},
    )
    success_state = make_engine(registry, success_config).run(WorkflowState(user_question="hook"))

    error_config = make_config(
        nodes={"first": NodeConfig(type="hook_explode")},
        edges={"first": EdgeConfig(terminal=True)},
    )
    error_state = make_engine(registry, error_config).run(WorkflowState(user_question="hook error"))

    assert success_state.data["hooked"] is True
    assert error_state.termination_reason == "node_error"
    assert HookNode.events == [
        "before:first",
        "run:first",
        "after:first:success",
        "before:first",
        "run:first",
        "error:first:hook boom",
    ]


def test_trace_summary_records_string_hash_without_raw_sql_preview() -> None:
    registry = NodeRegistry()
    registry.register("sql_summary", SqlSummaryNode)
    config = make_config(
        nodes={"first": NodeConfig(type="sql_summary")},
        edges={"first": EdgeConfig(terminal=True)},
    )

    state = make_engine(registry, config).run(WorkflowState(user_question="列出订单金额"))

    output_summary = state.trace[0].output_summary
    serialized_summary = json.dumps(output_summary, ensure_ascii=False)
    assert "SELECT id, amount FROM orders" not in serialized_summary
    output_sql = output_summary["output"]["generated_sql"]
    state_sql = output_summary["state_patch"]["data"]["current_sql"]
    assert output_sql["type"] == "str"
    assert output_sql["length"] == len("SELECT id, amount FROM orders")
    assert output_sql["hash"].startswith("sha256:")
    assert "preview" not in output_sql
    assert state_sql["hash"] == output_sql["hash"]
