from fastapi.testclient import TestClient

from text_to_sql_demo.main import create_app


def test_health_endpoint_returns_ok() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "text-to-sql-demo"}


def test_transpile_endpoint_converts_existing_sql() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/transpile",
        json={
            "sql": "SELECT DATE_FORMAT(order_date, '%Y-%m-%d') FROM orders",
            "source_dialect": "mysql",
            "target_dialect": "postgres",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_dialect"] == "mysql"
    assert payload["target_dialect"] == "postgres"
    assert payload["normalized_sql"] == "SELECT DATE_FORMAT(order_date, '%Y-%m-%d') FROM orders"
    assert (
        payload["rendered_sql"]
        == "SELECT TO_CHAR(CAST(order_date AS TIMESTAMP), 'YYYY-MM-DD') FROM orders"
    )
