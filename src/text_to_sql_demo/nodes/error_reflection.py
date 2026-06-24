from text_to_sql_demo.observability.events import log_repair_attempted, log_repair_exhausted
from text_to_sql_demo.reflection import (
    ReflectionDecision,
    ReflectionStrategy,
    append_sql_context,
    build_sql_attempt_context,
    decide_reflection_strategy,
    reflection_outcome,
)
from text_to_sql_demo.sql.models import RepairInstruction, SQLError
from text_to_sql_demo.sql.repair import strategy_for_error
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("reflection_decision")
@register_node("error_reflection")
@register_node("error_classification")
class ReflectionDecisionNode(BaseNode):
    """把 SQL 错误反思为可路由的策略决策。"""

    def run(self, state: WorkflowState) -> NodeResult:
        attempt_count = int(state.data.get("attempt_count", 0))
        max_attempts = _max_attempts(self.config, state)
        last_error = SQLError.model_validate(state.data["last_error"])
        attempts_exhausted = attempt_count >= max_attempts
        decision = decide_reflection_strategy(
            error=last_error,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            attempts_exhausted=attempts_exhausted,
        )
        sql_context = build_sql_attempt_context(
            state_data=state.data,
            decision=decision,
            attempt=_context_attempt_number(
                attempt_count=attempt_count,
                attempts_exhausted=attempts_exhausted,
            ),
        )
        next_sql_contexts = append_sql_context(state.data.get("sql_contexts"), sql_context)
        patch = {
            "reflection_decision": decision.model_dump(mode="json"),
            "sql_contexts": next_sql_contexts,
            "last_reflection_strategy": decision.strategy.value,
            "last_error": last_error.model_dump(mode="python"),
        }

        if attempts_exhausted:
            log_repair_exhausted(
                request_id=state.request_id,
                node_name=self.name,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
                error_category=last_error.category,
            )
            patch["termination_reason"] = "attempts_exhausted"
            return NodeResult(
                outcome="attempts_exhausted",
                state_patch={"data": patch},
                output={"reflection_decision": patch["reflection_decision"]},
            )

        log_repair_attempted(
            request_id=state.request_id,
            node_name=self.name,
            attempt_count=attempt_count + 1,
            max_attempts=max_attempts,
            error_category=last_error.category,
        )
        instruction = _repair_instruction(
            state=state,
            last_error=last_error,
            decision=decision,
        )
        patch["repair_instruction"] = instruction.model_dump(mode="python")
        if decision.strategy in {
            ReflectionStrategy.RELINK_SCHEMA,
            ReflectionStrategy.RETRIEVE_CONTEXT,
        }:
            patch["attempt_count"] = attempt_count + 1

        return NodeResult(
            outcome=reflection_outcome(decision),
            state_patch={"data": patch},
            output={
                "reflection_decision": patch["reflection_decision"],
                "repair_instruction": patch["repair_instruction"],
            },
        )


def _max_attempts(config: dict, state: WorkflowState) -> int:
    configured_max_attempts = config.get("max_repair_attempts")
    if configured_max_attempts is None:
        configured_max_attempts = state.data.get("max_repair_attempts")
    return int(configured_max_attempts if configured_max_attempts is not None else 3)


def _context_attempt_number(*, attempt_count: int, attempts_exhausted: bool) -> int:
    if attempts_exhausted and attempt_count > 0:
        return attempt_count
    return attempt_count + 1


def _repair_instruction(
    *,
    state: WorkflowState,
    last_error: SQLError,
    decision: ReflectionDecision,
) -> RepairInstruction:
    strategy = strategy_for_error(last_error)
    return RepairInstruction(
        original_question=state.user_question,
        current_sql=str(state.data.get("current_sql") or state.data.get("generated_sql")),
        error_category=last_error.category,
        original_error=last_error.raw_message or last_error.message,
        related_schema=state.data.get("schema_linking") or state.data.get("schema") or {},
        repair_history=list(state.data.get("repair_history", [])),
        reason=decision.reason,
        strategy=strategy,
    )


ReflectErrorNode = ReflectionDecisionNode
