from collections.abc import Callable

from text_to_sql_demo.workflow.exceptions import (
    DuplicateNodeRegistrationError,
    NodeRegistrationError,
)
from text_to_sql_demo.workflow.node import BaseNode

NodeClass = type[BaseNode]


class NodeRegistry:
    """维护节点类型名称到节点类的映射。"""

    def __init__(self) -> None:
        self._node_classes: dict[str, NodeClass] = {}

    def register(self, node_type: str, node_class: NodeClass) -> None:
        """用可配置的节点类型名称注册节点类。"""
        if not issubclass(node_class, BaseNode):
            raise TypeError(f"注册类必须继承 BaseNode: {node_class!r}")
        if node_type in self._node_classes:
            raise DuplicateNodeRegistrationError(f"节点类型重复注册: {node_type}")
        self._node_classes[node_type] = node_class

    def contains(self, node_type: str) -> bool:
        """判断节点类型是否已注册。"""
        return node_type in self._node_classes

    def get(self, node_type: str) -> NodeClass:
        """返回已注册节点类；未注册时抛出清晰的配置错误。"""
        try:
            return self._node_classes[node_type]
        except KeyError as exc:
            available_types = ", ".join(sorted(self._node_classes)) or "<none>"
            raise NodeRegistrationError(
                f"节点类型未注册: {node_type}; 可用类型: {available_types}"
            ) from exc


default_registry = NodeRegistry()


def register_node(
    node_type: str,
    *,
    registry: NodeRegistry | None = None,
) -> Callable[[NodeClass], NodeClass]:
    """装饰 BaseNode 子类，并把它注册到 registry。"""
    target_registry = registry or default_registry

    def decorator(node_class: NodeClass) -> NodeClass:
        target_registry.register(node_type, node_class)
        return node_class

    return decorator
