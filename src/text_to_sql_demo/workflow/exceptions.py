from text_to_sql_demo.exceptions import (
    TextToSQLDemoError,
)
from text_to_sql_demo.exceptions import (
    WorkflowConfigurationError as ProjectWorkflowConfigurationError,
)

WorkflowConfigurationError = ProjectWorkflowConfigurationError


class WorkflowErrorBase(TextToSQLDemoError):
    """工作流核心异常基类。"""


class NodeRegistrationError(WorkflowErrorBase):
    """工作流节点类型未注册时抛出。"""


class DuplicateNodeRegistrationError(NodeRegistrationError):
    """工作流节点类型重复注册时抛出。"""
