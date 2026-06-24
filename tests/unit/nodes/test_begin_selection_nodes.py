from text_to_sql_demo.nodes.begin import BeginNode
from text_to_sql_demo.nodes.selection import SelectionNode
from text_to_sql_demo.workflow.state import WorkflowState


def test_begin_node_initializes_workflow_context() -> None:
    state = WorkflowState(user_question="列出订单金额")

    result = BeginNode(name="begin", node_type="begin").run(state)

    assert result.outcome == "success"
    assert result.state_patch["data"]["task"]["question"] == "列出订单金额"
    assert result.state_patch["data"]["task"]["request_id"] == state.request_id
    assert result.output["task"]["workflow_entry"] == "begin"


def test_selection_node_routes_text_to_sql_by_default() -> None:
    state = WorkflowState(user_question="列出订单金额")

    result = SelectionNode(name="selection", node_type="selection").run(state)

    assert result.outcome == "text_to_sql"
    assert result.state_patch["data"]["intent"]["type"] == "text_to_sql"
    assert result.state_patch["data"]["intent"]["reason"] == "default_text_to_sql"
