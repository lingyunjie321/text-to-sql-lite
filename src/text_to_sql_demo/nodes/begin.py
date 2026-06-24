from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("begin")
class BeginNode(BaseNode):
    """初始化一次 Text-to-SQL 任务的基础上下文。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """写入后续节点共享的任务元信息。"""
        payload = {
            "question": state.user_question,
            "request_id": state.request_id,
            "workflow_entry": self.name,
        }
        return NodeResult(
            outcome="success",
            state_patch={"data": {"task": payload}},
            output={"task": payload},
        )
