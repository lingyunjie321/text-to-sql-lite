from pathlib import Path

from fastapi.testclient import TestClient

from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.main import create_app

SCENARIO_A_QUESTION = (
    "统计每个地区订单金额最高的 3 个客户，"
    "返回地区、客户名称、总金额和地区内排名。"
)
SCENARIO_A_SQL = """
SELECT region, customer_name, total_amount, region_rank
FROM (
  SELECT region, customer_name, total_amount,
         RANK() OVER (PARTITION BY region ORDER BY total_amount DESC) AS region_rank
  FROM (
    SELECT r.name AS region, c.name AS customer_name, SUM(o.amount) AS total_amount
    FROM regions r
    JOIN customers c ON c.region_id = r.id
    JOIN orders o ON o.customer_id = c.id
    GROUP BY r.name, c.name
  ) totals
) ranked
WHERE region_rank <= 3
ORDER BY region, region_rank
""".strip()

SCENARIO_B_WRONG_SQL = "SELECT region_id, SUM(total_amount) FROM orders GROUP BY region_id"
SCENARIO_B_FIXED_SQL = """
SELECT r.name AS region, SUM(o.amount) AS total_amount
FROM regions r
JOIN customers c ON c.region_id = r.id
JOIN orders o ON o.customer_id = c.id
GROUP BY r.name
ORDER BY r.name
""".strip()

ALWAYS_WRONG_SQL = "SELECT missing_amount FROM missing_orders"


def make_client(tmp_path: Path, llm_client: MockLLMClient) -> TestClient:
    return TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'demo.db'}",
            llm_client=llm_client,
        )
    )


def test_scenario_a_complex_query_succeeds_once(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        MockLLMClient(responses={"strong": SCENARIO_A_SQL, "light": SCENARIO_A_SQL}),
    )

    response = client.post(
        "/api/v1/query",
        json={
            "question": SCENARIO_A_QUESTION,
            "target_dialect": "sqlite",
            "max_attempts": 3,
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    linked_tables = {table["name"] for table in payload["linked_schema"]["tables"]}
    trace_nodes = [event["node_name"] for event in payload["trace"]]

    assert payload["status"] == "success"
    assert payload["attempts"] == 0
    assert payload["selected_model"] == "strong"
    assert {"regions", "customers", "orders"} <= linked_tables
    assert "SUM(" in payload["final_sql"]
    assert "RANK() OVER" in payload["final_sql"]
    assert payload["result"]["columns"] == [
        "region",
        "customer_name",
        "total_amount",
        "region_rank",
    ]
    assert "fix" not in trace_nodes


def test_scenario_b_wrong_field_is_reflected_and_fixed(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        MockLLMClient(sequence=[SCENARIO_B_WRONG_SQL, SCENARIO_B_FIXED_SQL]),
    )

    response = client.post(
        "/api/v1/query",
        json={
            "question": "统计每个地区的订单总金额。",
            "target_dialect": "sqlite",
            "max_attempts": 3,
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    trace_outcomes = [event["outcome"] for event in payload["trace"]]

    assert payload["status"] == "success"
    assert payload["attempts"] == 1
    assert payload["repair_history"][0]["old_sql"] == SCENARIO_B_WRONG_SQL
    assert payload["repair_history"][0]["new_sql"] == SCENARIO_B_FIXED_SQL
    assert payload["repair_history"][0]["error_type"] in {"unknown_column", "unknown_table"}
    assert "JOIN customers" in payload["final_sql"]
    assert "JOIN orders" in payload["final_sql"]
    assert "SUM(o.amount)" in payload["final_sql"]
    assert "validation_failed" in trace_outcomes
    assert "reflect_retry" in trace_outcomes
    assert "fix_complete" in trace_outcomes
    assert payload["result"]["columns"] == ["region", "total_amount"]


def test_scenario_c_stops_after_three_failed_repairs(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        MockLLMClient(default_response=ALWAYS_WRONG_SQL),
    )

    response = client.post(
        "/api/v1/query",
        json={
            "question": "统计每个地区的订单总金额。",
            "target_dialect": "sqlite",
            "max_attempts": 3,
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "failed"
    assert payload["attempts"] == 3
    assert len(payload["repair_history"]) == 3
    assert payload["errors"][-1]["error"]["category"] in {"unknown_table", "unknown_column"}
    assert payload["trace"][-2]["outcome"] == "attempts_exhausted"
    assert payload["trace"][-1]["node_name"] == "finalization"
