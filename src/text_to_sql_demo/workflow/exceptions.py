class WorkflowErrorBase(Exception):
    """工作流核心异常基类。"""


class NodeRegistrationError(WorkflowErrorBase):
    """工作流节点类型未注册时抛出。"""


class DuplicateNodeRegistrationError(NodeRegistrationError):
    """工作流节点类型重复注册时抛出。"""


class WorkflowConfigurationError(WorkflowErrorBase):
    """工作流配置无法执行时抛出。"""
