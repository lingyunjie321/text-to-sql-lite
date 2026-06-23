import pytest

from text_to_sql_demo.exceptions import (
    ConfigurationError,
    CredentialMissingError,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseExecutionError,
    LLMConfigurationError,
    LLMProviderError,
    NodeExecutionError,
    TextToSQLDemoError,
    WorkflowConfigurationError,
)
from text_to_sql_demo.workflow.exceptions import (
    WorkflowConfigurationError as WorkflowModuleConfigurationError,
)


def test_project_exceptions_share_common_base() -> None:
    """核心异常应能被项目基础异常统一捕获。"""
    exception_types = [
        ConfigurationError,
        CredentialMissingError,
        DatabaseConfigurationError,
        DatabaseConnectionError,
        DatabaseExecutionError,
        LLMConfigurationError,
        LLMProviderError,
        WorkflowConfigurationError,
        NodeExecutionError,
    ]

    for exception_type in exception_types:
        assert issubclass(exception_type, TextToSQLDemoError)


def test_configuration_related_exceptions_share_configuration_base() -> None:
    """配置和凭据类异常应能被配置异常统一捕获。"""
    assert issubclass(CredentialMissingError, ConfigurationError)
    assert issubclass(DatabaseConfigurationError, ConfigurationError)
    assert issubclass(LLMConfigurationError, ConfigurationError)
    assert issubclass(WorkflowConfigurationError, ConfigurationError)


def test_workflow_configuration_error_keeps_existing_import_path() -> None:
    """旧 workflow 异常导入路径应继续指向项目配置异常体系。"""
    assert WorkflowModuleConfigurationError is WorkflowConfigurationError

    with pytest.raises(TextToSQLDemoError):
        raise WorkflowModuleConfigurationError("节点配置错误")

