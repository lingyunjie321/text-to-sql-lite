from text_to_sql_demo.observability.events import log_repair_attempted, log_repair_exhausted
from text_to_sql_demo.sql.models import RepairInstruction, SQLError
from text_to_sql_demo.sql.repair import strategy_for_error
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("error_reflection")
@register_node("error_classification")
class ReflectErrorNode(BaseNode):
    """把 SQL 错误反思为结构化修复指令。"""

    def run(self, state: WorkflowState) -> NodeResult:
        attempt_count = int(state.data.get("attempt_count", 0))
        configured_max_attempts = self.config.get("max_repair_attempts")
        if configured_max_attempts is None:
            configured_max_attempts = state.data.get("max_repair_attempts")
        max_attempts = int(configured_max_attempts if configured_max_attempts is not None else 3)
        last_error = SQLError.model_validate(state.data["last_error"])
        if attempt_count >= max_attempts:
            log_repair_exhausted(
                request_id=state.request_id,
                node_name=self.name,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
                error_category=last_error.category,
            )
            return NodeResult(
                outcome="attempts_exhausted",
                state_patch={
                    "data": {
                        "termination_reason": "attempts_exhausted",
                        "last_error": last_error.model_dump(mode="python"),
                    }
                },
            )

        log_repair_attempted(
            request_id=state.request_id,
            node_name=self.name,
            attempt_count=attempt_count + 1,
            max_attempts=max_attempts,
            error_category=last_error.category,
        )
        strategy = strategy_for_error(last_error)
        instruction = RepairInstruction(
            original_question=state.user_question,
            current_sql=str(state.data.get("current_sql") or state.data.get("generated_sql")),
            error_category=last_error.category,
            original_error=last_error.raw_message or last_error.message,
            related_schema=state.data.get("schema_linking") or state.data.get("schema") or {},
            repair_history=list(state.data.get("repair_history", [])),
            reason=f"根据 {strategy.name} 策略修复 SQL",
            strategy=strategy,
        )
        return NodeResult(
            outcome="reflect_retry",
            state_patch={"data": {"repair_instruction": instruction.model_dump(mode="python")}},
            output={"repair_instruction": instruction.model_dump(mode="python")},
        )
