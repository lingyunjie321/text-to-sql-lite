class TextToSQLDemoError(Exception):
    """项目运行时异常基类。"""


class ConfigurationError(TextToSQLDemoError):
    """配置读取、校验或引用错误。"""


class CredentialMissingError(ConfigurationError):
    """环境变量凭据缺失。"""


class DatabaseConfigurationError(ConfigurationError):
    """数据库连接配置错误。"""


class DatabaseConnectionError(TextToSQLDemoError):
    """数据库连接阶段错误。"""


class DatabaseExecutionError(TextToSQLDemoError):
    """数据库执行阶段错误。"""


class MetadataStoreError(TextToSQLDemoError):
    """内部 metadata store 读写失败。"""


class LLMConfigurationError(ConfigurationError):
    """LLM provider 配置错误。"""


class LLMProviderError(TextToSQLDemoError):
    """LLM provider 调用错误。"""


class WorkflowConfigurationError(ConfigurationError):
    """工作流配置无法执行时抛出。"""


class NodeExecutionError(TextToSQLDemoError):
    """节点执行阶段错误。"""
