import ast
from pathlib import Path

WORKFLOW_DIR = Path("src/text_to_sql_demo/workflow")
GUARDED_FILES = [
    WORKFLOW_DIR / "engine.py",
    WORKFLOW_DIR / "factory.py",
]
FORBIDDEN_NODE_CLASS_NAMES = {
    "GenerateSQLNode",
    "ExecuteSQLNode",
    "ValidateSQLNode",
    "ReflectErrorNode",
    "FixSQLNode",
}


def parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_engine_and_factory_do_not_import_concrete_nodes() -> None:
    for path in GUARDED_FILES:
        tree = parse_module(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("text_to_sql_demo.nodes")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("text_to_sql_demo.nodes")


def test_engine_and_factory_do_not_instantiate_concrete_node_classes() -> None:
    for path in GUARDED_FILES:
        tree = parse_module(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in FORBIDDEN_NODE_CLASS_NAMES


def test_engine_and_factory_do_not_branch_on_specific_node_type_literals() -> None:
    for path in GUARDED_FILES:
        tree = parse_module(path)
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Match)
            if isinstance(node, ast.If):
                compared_literals = [
                    child.value
                    for child in ast.walk(node.test)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)
                ]
                node_type_names = [
                    child.id
                    for child in ast.walk(node.test)
                    if isinstance(child, ast.Name) and child.id in {"node_type", "type"}
                ]
                node_type_attrs = [
                    child.attr
                    for child in ast.walk(node.test)
                    if isinstance(child, ast.Attribute) and child.attr == "type"
                ]
                assert not (
                    compared_literals
                    and (node_type_names or node_type_attrs)
                ), f"{path} branches on node type literals: {compared_literals}"
