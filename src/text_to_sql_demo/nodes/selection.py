from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("selection")
class SelectionNode(BaseNode):
    """识别用户意图，并把工作流路由到对应分支。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """第一阶段默认将请求识别为 Text-to-SQL。"""
        intent = {
            "type": "text_to_sql",
            "reason": "default_text_to_sql",
            "question_length": len(state.user_question),
        }
        return NodeResult(
            outcome="text_to_sql",
            state_patch={"data": {"intent": intent}},
            output={"intent": intent},
        )
