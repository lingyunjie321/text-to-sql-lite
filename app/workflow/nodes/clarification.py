"""澄清节点：业务对象不唯一时不生成 SQL，返回结构化澄清请求。"""

from __future__ import annotations

from app.connectors.errors import ErrorType
from app.workflow.models import (
    Clarification,
    SQLTaskState,
    WorkflowContext,
)
from app.workflow.nodes._common import NodeUpdate


def _clarification(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    code = (
        "AMBIGUOUS_SEMANTICS"
        if state.error_type is ErrorType.AMBIGUOUS_SEMANTICS
        else "BUSINESS_KNOWLEDGE_MISSING"
    )
    return {
        "clarification": Clarification(
            code=code,
            question=(
                "Please clarify the requested business meaning "
                "or reporting scope."
            ),
        ),
        "public_error": None,
    }
