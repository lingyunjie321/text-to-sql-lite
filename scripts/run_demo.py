import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DATABASE_URL = f"sqlite:///{PROJECT_ROOT / 'data' / 'sqlite' / 'demo.db'}"

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


def main() -> int:
    """运行三个无需 API Key 的面试演示场景。"""
    sys.path.insert(0, str(SRC_DIR))

    from text_to_sql_demo.api.models import QueryRequest
    from text_to_sql_demo.api.service import TextToSQLApiService
    from text_to_sql_demo.llm.client import MockLLMClient

    scenarios = [
        (
            "Scenario A: 复杂查询一次成功",
            QueryRequest(
                question=SCENARIO_A_QUESTION,
                target_dialect="sqlite",
                max_attempts=3,
                debug=True,
            ),
            MockLLMClient(responses={"strong": SCENARIO_A_SQL, "light": SCENARIO_A_SQL}),
        ),
        (
            "Scenario B: 错误字段自动修复",
            QueryRequest(
                question="统计每个地区的订单总金额。",
                target_dialect="sqlite",
                max_attempts=3,
                debug=True,
            ),
            MockLLMClient(sequence=[SCENARIO_B_WRONG_SQL, SCENARIO_B_FIXED_SQL]),
        ),
        (
            "Scenario C: 达到终止条件",
            QueryRequest(
                question="统计每个地区的订单总金额。",
                target_dialect="sqlite",
                max_attempts=3,
                debug=True,
            ),
            MockLLMClient(default_response=ALWAYS_WRONG_SQL),
        ),
    ]

    for title, request, llm_client in scenarios:
        service = TextToSQLApiService(database_url=DATABASE_URL, llm_client=llm_client)
        payload = service.run_query(request)
        _print_payload(title, payload)

    return 0


def _print_payload(title: str, payload: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(f"request_id: {payload['request_id']}")
    print(f"status: {payload['status']}")
    print(f"selected_model: {payload['selected_model']}")
    print(f"attempts: {payload['attempts']}")
    print("final_sql:")
    print(payload["final_sql"])
    result = payload.get("result") or {}
    print(f"columns: {result.get('columns')}")
    print(f"row_count: {len(result.get('rows') or [])}")
    if payload["repair_history"]:
        print("repair_history:")
        for item in payload["repair_history"]:
            print(
                f"  attempt={item['attempt']} error={item['error_type']} "
                f"old={item['old_sql']} new={item['new_sql']}"
            )
    if payload["errors"]:
        print(f"errors: {payload['errors']}")
    print("trace:")
    for event in payload["trace"]:
        print(f"  {event['node_name']} -> {event['outcome']} ({event['status']})")


if __name__ == "__main__":
    raise SystemExit(main())
