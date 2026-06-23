from collections.abc import Mapping
from typing import Any

from text_to_sql_demo.config.models import NodeConfig
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.node import BaseNode
from text_to_sql_demo.workflow.registry import NodeRegistry, default_registry


class NodeFactory:
    """通过 registry 创建节点实例，避免按 node type 分支。"""

    def __init__(
        self,
        *,
        registry: NodeRegistry | None = None,
        dependencies: NodeDependencies | Mapping[str, Any] | None = None,
    ) -> None:
        self.registry = registry or default_registry
        if isinstance(dependencies, NodeDependencies):
            self.dependencies = dependencies
        else:
            self.dependencies = NodeDependencies(values=dependencies or {})

    def create(self, *, name: str, config: NodeConfig) -> BaseNode:
        """创建已配置的节点实例。"""
        node_class = self.registry.get(config.type)
        node_config = config.model_dump(mode="python")
        node_config.pop("type", None)
        return node_class(
            name=name,
            node_type=config.type,
            config=node_config,
            dependencies=self.dependencies,
        )
