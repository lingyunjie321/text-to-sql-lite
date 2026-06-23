from pathlib import Path

from text_to_sql_demo.retrieval.examples import ExampleStore


def test_example_store_respects_top_k() -> None:
    store = ExampleStore.from_yaml(Path("configs/examples.yaml"))

    results = store.search(
        query="统计每个地区订单金额",
        dialect="sqlite",
        top_k=2,
        involved_tables=["regions", "customers", "orders"],
    )

    assert len(results) == 2
    assert results[0].score >= results[1].score
    assert results[0].example.natural_language == "统计每个地区订单金额"
    assert results[0].reasons


def test_example_store_filters_by_dialect() -> None:
    store = ExampleStore.from_yaml(Path("configs/examples.yaml"))

    sqlite_results = store.search(query="订单金额", dialect="sqlite", top_k=10)
    postgres_results = store.search(query="订单金额", dialect="postgres", top_k=10)

    assert sqlite_results
    assert postgres_results
    assert {result.example.dialect for result in sqlite_results} == {"sqlite"}
    assert {result.example.dialect for result in postgres_results} == {"postgres"}
