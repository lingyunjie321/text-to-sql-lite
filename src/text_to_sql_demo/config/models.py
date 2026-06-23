from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowSection(BaseModel):
    """顶层工作流执行设置。"""

    name: str
    start_node: str
    max_steps: int = Field(default=30, gt=0)
    max_repair_attempts: int = Field(default=3, ge=0)


class DialectConfig(BaseModel):
    """后续校验阶段使用的 SQL 方言设置。"""

    name: str = "sqlite"
    allow_transpile: bool = False
    target_dialect: str = "sqlite"


class DatabaseConnectionConfig(BaseModel):
    """具名数据库连接配置。"""

    driver: Literal["sqlite", "postgresql"] = "sqlite"
    url_env: str | None = None
    fallback_url: str
    read_only: bool = True


class DatabaseConfig(BaseModel):
    """数据库连接集合。"""

    default: str
    connections: dict[str, DatabaseConnectionConfig]


class ModelAliasConfig(BaseModel):
    """隐藏在 alias 后面的 provider 模型设置。"""

    provider: str
    model: str
    temperature: float = 0.0


class ModelsConfig(BaseModel):
    """已配置的 LLM 模型 alias。"""

    aliases: dict[str, ModelAliasConfig] = Field(default_factory=dict)


class SchemaLinkingConfig(BaseModel):
    """用于 prompt pruning 的 Schema Linking 限制。"""

    max_tables: int = Field(default=6, gt=0)
    max_columns_per_table: int = Field(default=12, gt=0)
    include_foreign_keys: bool = True


class SchemaConfig(BaseModel):
    """Schema 元数据来源设置。"""

    catalog_source: Literal["database", "yaml"] = "database"
    catalog_path: str | None = None
    linking: SchemaLinkingConfig = Field(default_factory=SchemaLinkingConfig)


class RetrievalConfig(BaseModel):
    """历史 SQL 检索设置。"""

    examples_path: str = "data/examples/historical_sql.jsonl"
    top_k: int = Field(default=5, gt=0)
    strategy: str = "lexical_overlap"


class TraceConfig(BaseModel):
    """Trace 输出控制项。"""

    enabled: bool = True
    include_prompt_summary: bool = True
    include_sql: bool = True
    include_result_preview: bool = True
    max_result_preview_rows: int = Field(default=5, ge=0)


class NodeConfig(BaseModel):
    """已配置的工作流节点声明。"""

    model_config = ConfigDict(extra="allow")

    type: str


class EdgeConfig(BaseModel):
    """工作流节点的具名流转目标。"""

    model_config = ConfigDict(extra="allow")

    on_success: str | None = None
    on_failure: str | None = None
    on_retriable: str | None = None
    on_non_retriable: str | None = None
    on_attempts_exhausted: str | None = None
    terminal: bool = False

    def targets(self) -> list[str]:
        """返回已配置的非终止流转目标。"""
        built_in_targets = [
            target
            for target in (
                self.on_success,
                self.on_failure,
                self.on_retriable,
                self.on_non_retriable,
                self.on_attempts_exhausted,
            )
            if target is not None
        ]
        custom_targets = [
            value
            for key, value in (self.model_extra or {}).items()
            if key.startswith("on_") and isinstance(value, str)
        ]
        return [*built_in_targets, *custom_targets]

    def target_for(self, outcome: str) -> str | None:
        """返回指定节点 outcome 对应的流转目标。"""
        field_name = f"on_{outcome}"
        built_in_target = getattr(self, field_name, None)
        if isinstance(built_in_target, str):
            return built_in_target

        custom_target = (self.model_extra or {}).get(field_name)
        if isinstance(custom_target, str):
            return custom_target

        return None


class WorkflowConfig(BaseModel):
    """从 workflow.yaml 加载并校验后的配置。"""

    model_config = ConfigDict(populate_by_name=True)

    workflow: WorkflowSection
    dialect: DialectConfig = Field(default_factory=DialectConfig)
    database: DatabaseConfig
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    schema_config: SchemaConfig = Field(default_factory=SchemaConfig, alias="schema")
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    nodes: dict[str, NodeConfig]
    edges: dict[str, EdgeConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "WorkflowConfig":
        """不构造工作流引擎，仅校验静态引用。"""
        if self.database.default not in self.database.connections:
            raise ValueError(f"未知默认数据库: {self.database.default}")

        if self.workflow.start_node not in self.nodes:
            raise ValueError(f"未知 start_node: {self.workflow.start_node}")

        for node_name, edge_config in self.edges.items():
            if node_name not in self.nodes:
                raise ValueError(f"未知 edge source: {node_name}")

            for target in edge_config.targets():
                if target not in self.nodes:
                    raise ValueError(f"未知 edge target: {target}")

        return self

    def model_aliases(self) -> dict[str, dict[str, Any]]:
        """按 alias 返回 provider 配置，供需要普通 mapping 的调用方使用。"""
        return {
            alias: config.model_dump()
            for alias, config in self.models.aliases.items()
        }
