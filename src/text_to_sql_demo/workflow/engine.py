from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from text_to_sql_demo.config.models import WorkflowConfig
from text_to_sql_demo.observability.context import (
    set_node_context,
    set_request_context,
    set_workflow_context,
)
from text_to_sql_demo.observability.events import (
    log_node_completed,
    log_node_failed,
    log_node_started,
    log_workflow_completed,
    log_workflow_failed,
    log_workflow_started,
)
from text_to_sql_demo.workflow.exceptions import WorkflowConfigurationError
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.state import TraceEvent, WorkflowError, WorkflowState


class WorkflowEngine:
    """执行配置中的工作流节点，直到到达终止条件。"""

    def __init__(self, *, config: WorkflowConfig, node_factory: NodeFactory) -> None:
        self.config = config
        self.node_factory = node_factory

    def run(self, state: WorkflowState | None = None) -> WorkflowState:
        """运行配置好的工作流并返回最终状态。"""
        workflow_state = state or WorkflowState()
        set_request_context(request_id=workflow_state.request_id)
        set_workflow_context(workflow_name=self.config.workflow.name)
        workflow_started = perf_counter()
        log_workflow_started(
            request_id=workflow_state.request_id,
            workflow_name=self.config.workflow.name,
        )
        current_node = self.config.workflow.start_node

        while not workflow_state.terminated:
            if workflow_state.step_count >= self.config.workflow.max_steps:
                workflow_state.terminate("max_steps_exceeded")
                break

            node_config = self.config.nodes.get(current_node)
            if node_config is None:
                raise WorkflowConfigurationError(f"工作流节点未配置: {current_node}")

            node = self.node_factory.create(name=current_node, config=node_config)
            workflow_state.current_node = current_node

            result, trace = self._execute_node(node=node, state=workflow_state)
            workflow_state.trace.append(trace)
            workflow_state.step_count += 1

            if trace.status == "error":
                workflow_state.terminate("node_error")
                break

            if result.terminate:
                workflow_state.terminate(result.termination_reason or result.outcome)
                break

            next_node = self._resolve_next_node(current_node, result.outcome)
            workflow_state.last_outcome = result.outcome
            workflow_state.next_node = next_node

            if next_node is None:
                workflow_state.terminate("terminal")
                break

            current_node = next_node

        duration_ms = int((perf_counter() - workflow_started) * 1000)
        if workflow_state.errors or workflow_state.termination_reason in {
            "max_steps_exceeded",
            "node_error",
        }:
            log_workflow_failed(
                request_id=workflow_state.request_id,
                workflow_name=self.config.workflow.name,
                termination_reason=workflow_state.termination_reason,
                duration_ms=duration_ms,
            )
        else:
            log_workflow_completed(
                request_id=workflow_state.request_id,
                workflow_name=self.config.workflow.name,
                termination_reason=workflow_state.termination_reason,
                duration_ms=duration_ms,
            )

        set_node_context(node_name=None, node_type=None)
        set_workflow_context(workflow_name=None)
        return workflow_state

    def _execute_node(
        self,
        *,
        node: BaseNode,
        state: WorkflowState,
    ) -> tuple[NodeResult, TraceEvent]:
        started_at = datetime.now(UTC)
        started_timer = perf_counter()
        result = NodeResult(outcome="error")
        status = "error"
        error_message: str | None = None
        structured_error: dict[str, Any] | None = None
        caught_error: BaseException | None = None
        input_summary = _summarize_node_input(state)
        step = state.step_count + 1
        set_node_context(node_name=node.name, node_type=node.node_type)
        log_node_started(
            request_id=state.request_id,
            workflow_name=self.config.workflow.name,
            node_name=node.name,
            node_type=node.node_type,
            step=step,
        )

        try:
            node.before(state)
            result = node.run(state)
            state.apply_patch(result.state_patch)
            node.after(state, result)
            status = "success"
        except Exception as exc:  # noqa: BLE001 - 工作流必须记录任意节点失败。
            error_message = str(exc)
            structured_error = {
                "type": exc.__class__.__name__,
                "message": error_message,
            }
            state.errors.append(
                WorkflowError(
                    node_name=node.name,
                    error_type=exc.__class__.__name__,
                    message=error_message,
                )
            )
            node.error(state, exc)
            caught_error = exc

        ended_at = datetime.now(UTC)
        duration_ms = int((perf_counter() - started_timer) * 1000)
        if caught_error is None:
            log_node_completed(
                request_id=state.request_id,
                workflow_name=self.config.workflow.name,
                node_name=node.name,
                node_type=node.node_type,
                outcome=result.outcome,
                duration_ms=duration_ms,
                step=step,
            )
        else:
            log_node_failed(
                request_id=state.request_id,
                workflow_name=self.config.workflow.name,
                node_name=node.name,
                node_type=node.node_type,
                outcome=result.outcome,
                duration_ms=duration_ms,
                step=step,
                error=caught_error,
            )

        return result, TraceEvent(
            request_id=state.request_id,
            node_name=node.name,
            node_type=node.node_type,
            status=status,
            outcome=result.outcome,
            step=state.step_count + 1,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            input_summary=input_summary,
            output_summary=_summarize_node_output(result),
            error=structured_error,
            error_message=error_message,
        )

    def _resolve_next_node(self, node_name: str, outcome: str) -> str | None:
        edge_config = self.config.edges.get(node_name)
        if edge_config is None or edge_config.terminal:
            return None
        return edge_config.target_for(outcome)


def _summarize_node_input(state: WorkflowState) -> dict[str, Any]:
    """生成节点输入侧的轻量摘要，避免 Trace 携带完整大对象。"""
    current_sql_present = bool(
        state.data.get("current_sql") or state.data.get("generated_sql")
    )
    return {
        "question_length": len(state.user_question),
        "data_keys": sorted(state.data.keys()),
        "current_sql_present": current_sql_present,
        "attempt_count": int(state.data.get("attempt_count", 0)),
    }


def _summarize_node_output(result: NodeResult) -> dict[str, Any]:
    """生成节点输出侧的轻量摘要。"""
    return {
        "outcome": result.outcome,
        "output": _summarize_value(result.output),
        "state_patch": _summarize_value(result.state_patch),
        "terminate": result.terminate,
    }


def _summarize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _summarize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return {"type": "list", "count": len(value)}
    if isinstance(value, str):
        return {
            "type": "str",
            "length": len(value),
            "preview": value[:120],
        }
    return value
