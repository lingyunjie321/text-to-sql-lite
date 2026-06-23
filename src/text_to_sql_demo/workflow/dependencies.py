from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NodeDependencies:
    """统一注入给节点的共享依赖容器。"""

    values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", dict(self.values))

    def get(self, name: str, default: Any = None) -> Any:
        """按名称读取依赖，不存在时返回默认值。"""
        return self.values.get(name, default)
