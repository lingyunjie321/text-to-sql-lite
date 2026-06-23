from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.state import WorkflowState


class NodeResult(BaseModel):
    """每个工作流节点返回的结构化输出。"""

    outcome: str = "success"
    state_patch: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    terminate: bool = False
    termination_reason: str | None = None


class BaseNode(ABC):
    """所有工作流节点的基础接口。"""

    def __init__(
        self,
        *,
        name: str,
        config: Mapping[str, Any] | None = None,
        dependencies: NodeDependencies | None = None,
        node_type: str | None = None,
    ) -> None:
        self.name = name
        self.config = dict(config or {})
        self.dependencies = dependencies or NodeDependencies()
        self.node_type = node_type or self.__class__.__name__

    def before(self, state: WorkflowState) -> None:
        """run 前立即调用的生命周期钩子。"""

    @abstractmethod
    def run(self, state: WorkflowState) -> NodeResult:
        """执行节点并返回结构化结果。"""

    def after(self, state: WorkflowState, result: NodeResult) -> None:
        """run 成功后调用的生命周期钩子。"""

    def error(self, state: WorkflowState, error: Exception) -> None:
        """run 抛出异常时调用的生命周期钩子。"""
