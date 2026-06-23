from text_to_sql_demo.schema.catalog import DatabaseSchemaMetadata
from text_to_sql_demo.sql.validator import SQLValidator
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("sql_validation")
class ValidateSQLNode(BaseNode):
    """校验生成 SQL 的语法、安全性和 Schema 引用。"""

    def run(self, state: WorkflowState) -> NodeResult:
        sql = str(state.data.get("generated_sql") or state.data.get("current_sql") or "")
        schema = DatabaseSchemaMetadata.model_validate(state.data["schema"])
        dialect = str(
            state.data.get("target_dialect")
            or self.config.get("target_dialect")
            or "sqlite"
        )
        render_dialect = self.config.get("render_dialect") or state.data.get("render_dialect")
        allow_transpile = bool(self.config.get("allow_transpile", False))
        result = SQLValidator().validate(
            sql=sql,
            schema=schema,
            dialect=dialect,
            render_dialect=str(render_dialect) if render_dialect else None,
            allow_transpile=allow_transpile,
        )
        payload = result.model_dump(mode="python")
        if result.success:
            validated_sql = result.rendered_sql or result.normalized_sql or sql
            validated_sql_dialect = (
                str(render_dialect) if allow_transpile and render_dialect else dialect
            )
            return NodeResult(
                outcome="validation_success",
                state_patch={
                    "data": {
                        "validation_result": payload,
                        "normalized_sql": result.normalized_sql,
                        "rendered_sql": result.rendered_sql,
                        "validated_sql": validated_sql,
                        "validated_sql_dialect": validated_sql_dialect,
                        "current_sql": validated_sql,
                    }
                },
                output={"validation_result": payload},
            )

        error_payload = result.error.model_dump(mode="python") if result.error else None
        return NodeResult(
            outcome="validation_failed",
            state_patch={
                "data": {
                    "validation_result": payload,
                    "last_error": error_payload,
                    "current_sql": sql,
                }
            },
            output={"validation_result": payload},
        )
