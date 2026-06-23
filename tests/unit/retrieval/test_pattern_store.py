from pathlib import Path

from text_to_sql_demo.retrieval.patterns import BusinessPatternStore


def test_business_pattern_store_filters_by_dialect_and_ranks_matches(tmp_path: Path) -> None:
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(
        """
patterns:
  - name: sqlite_rank_by_region
    dialect: sqlite
    description: 地区内排名优先使用窗口函数
    pattern: RANK() OVER (PARTITION BY region ORDER BY total_amount DESC)
    tags: ["地区", "排名"]
    involved_tables: ["orders", "regions"]
  - name: postgres_rank_by_region
    dialect: postgres
    description: PostgreSQL 地区排名范式
    pattern: RANK() OVER (PARTITION BY region ORDER BY total_amount DESC)
    tags: ["地区", "排名"]
    involved_tables: ["orders", "regions"]
""",
        encoding="utf-8",
    )

    store = BusinessPatternStore.from_yaml(patterns_path)
    results = store.search(
        query="统计每个地区订单金额排名",
        dialect="sqlite",
        top_k=1,
        involved_tables=["orders", "regions"],
    )

    assert len(results) == 1
    assert results[0].pattern.name == "sqlite_rank_by_region"
    assert results[0].score > 0
    assert results[0].reasons
