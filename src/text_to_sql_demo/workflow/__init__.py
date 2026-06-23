"""通用工作流核心原语。"""

from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.engine import WorkflowEngine
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import NodeRegistry, register_node
from text_to_sql_demo.workflow.state import TraceEvent, WorkflowError, WorkflowState

__all__ = [
    "BaseNode",
    "NodeDependencies",
    "NodeFactory",
    "NodeRegistry",
    "NodeResult",
    "TraceEvent",
    "WorkflowEngine",
    "WorkflowError",
    "WorkflowState",
    "register_node",
]
