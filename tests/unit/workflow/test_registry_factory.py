import pytest

from text_to_sql_demo.config.models import NodeConfig
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.exceptions import (
    DuplicateNodeRegistrationError,
    NodeRegistrationError,
)
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import NodeRegistry, register_node
from text_to_sql_demo.workflow.state import WorkflowState


class DependencyAwareNode(BaseNode):
    """Fake node that proves dependencies are injected uniformly."""

    def run(self, state: WorkflowState) -> NodeResult:
        return NodeResult(
            outcome="success",
            state_patch={"data": {"answer": self.dependencies.get("answer")}},
        )


class OtherNode(BaseNode):
    """Second fake node for registry tests."""

    def run(self, state: WorkflowState) -> NodeResult:
        return NodeResult()


def test_factory_creates_registered_node_by_type() -> None:
    registry = NodeRegistry()
    registry.register("dependency_aware", DependencyAwareNode)
    factory = NodeFactory(
        registry=registry,
        dependencies=NodeDependencies(values={"answer": 42}),
    )

    node = factory.create(name="first", config=NodeConfig(type="dependency_aware"))
    result = node.run(WorkflowState(user_question="deps"))

    assert isinstance(node, DependencyAwareNode)
    assert result.state_patch["data"]["answer"] == 42


def test_registry_contains_registered_type() -> None:
    registry = NodeRegistry()
    registry.register("dependency_aware", DependencyAwareNode)

    assert registry.contains("dependency_aware") is True
    assert registry.contains("missing") is False


def test_duplicate_registration_raises_clear_error() -> None:
    registry = NodeRegistry()
    registry.register("dependency_aware", DependencyAwareNode)

    with pytest.raises(DuplicateNodeRegistrationError, match="节点类型重复注册: dependency_aware"):
        registry.register("dependency_aware", OtherNode)


def test_missing_registration_lists_available_types() -> None:
    registry = NodeRegistry()
    registry.register("dependency_aware", DependencyAwareNode)
    registry.register("other", OtherNode)

    with pytest.raises(NodeRegistrationError) as exc_info:
        registry.get("missing")

    message = str(exc_info.value)
    assert "节点类型未注册: missing" in message
    assert "可用类型: dependency_aware, other" in message


def test_register_node_decorator_uses_registry() -> None:
    registry = NodeRegistry()

    @register_node("decorated_dependency", registry=registry)
    class DecoratedDependencyNode(DependencyAwareNode):
        pass

    assert registry.get("decorated_dependency") is DecoratedDependencyNode
