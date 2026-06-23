from text_to_sql_demo.exceptions import TextToSQLDemoError


class RuntimeConfigError(TextToSQLDemoError):
    """运行时配置相关异常基类。"""


class RuntimeConfigNotFoundError(RuntimeConfigError):
    """请求的运行时配置不存在。"""


class RuntimeConfigExpiredError(RuntimeConfigError):
    """请求的运行时配置已经过期。"""


class RuntimeConfigInvalidError(RuntimeConfigError):
    """运行时配置内容不满足校验规则。"""


class RuntimeSecretMissingError(RuntimeConfigError):
    """运行时配置引用的密钥不存在。"""


class RuntimeProviderUnsupportedError(RuntimeConfigError):
    """运行时模型 provider 当前不支持。"""


class RuntimeConnectionTestError(RuntimeConfigError):
    """运行时连接测试失败。"""
