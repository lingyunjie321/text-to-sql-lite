import json
from pathlib import Path

from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.nodes.example_retrieval import ExampleRetrievalNode
from text_to_sql_demo.nodes.schema_linking import SchemaLinkingNode
from text_to_sql_demo.retrieval.examples import ExampleStore
from text_to_sql_demo.schema.catalog import read_schema_metadata
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.state import WorkflowState


def test_schema_linking_and_example_retrieval_results_are_state_serializable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "demo.db"
    initialize_database(db_path)
    schema = read_schema_metadata(f"sqlite:///{db_path}")
    state = WorkflowState(
        user_question="统计每个地区订单金额",
        data={"schema": schema.model_dump(mode="python")},
    )

    schema_node = SchemaLinkingNode(
        name="schema_linking",
        config={"top_k_tables": 3, "max_columns_per_table": 6},
    )
    schema_result = schema_node.run(state)
    state.apply_patch(schema_result.state_patch)

    retrieval_node = ExampleRetrievalNode(
        name="example_retrieval",
        config={"top_k": 2, "dialect": "sqlite"},
        dependencies=NodeDependencies(
            values={"example_store": ExampleStore.from_yaml(Path("configs/examples.yaml"))}
        ),
    )
    retrieval_result = retrieval_node.run(state)
    state.apply_patch(retrieval_result.state_patch)

    payload = state.model_dump(mode="json")
    json.dumps(payload)

    linked_tables = [table["name"] for table in payload["data"]["schema_linking"]["tables"]]
    assert linked_tables == ["orders", "regions", "customers"]
    assert len(payload["data"]["retrieved_examples"]) == 2
