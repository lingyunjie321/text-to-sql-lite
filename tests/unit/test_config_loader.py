from pathlib import Path

import pytest

from text_to_sql_demo.config.loader import load_workflow_config


def test_load_default_workflow_config() -> None:
    config = load_workflow_config(Path("workflow.yaml"))

    assert config.workflow.name == "interview_text_to_sql_demo"
    assert config.workflow.start_node == "begin"
    assert config.dialect.name == "sqlite"
    assert config.database.default == "demo_sqlite"
    assert config.schema_config.catalog_source == "database"
    assert config.retrieval.knowledge_path == "configs/knowledge.yaml"
    assert config.nodes["begin"].type == "begin"
    assert config.nodes["context_retrieval"].type == "context_retrieval"
    assert config.nodes["schema_linking"].type == "schema_linking"


def test_config_loader_rejects_edge_to_unknown_node(tmp_path: Path) -> None:
    config_file = tmp_path / "workflow.yaml"
    config_file.write_text(
        """
workflow:
  name: broken
  start_node: start
  max_steps: 10
  max_repair_attempts: 3
dialect:
  name: sqlite
database:
  default: demo
  connections:
    demo:
      driver: sqlite
      fallback_url: sqlite:///demo.db
schema:
  catalog_source: database
nodes:
  start:
    type: schema_linking
edges:
  start:
    on_success: missing
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="未知 edge target"):
        load_workflow_config(config_file)
