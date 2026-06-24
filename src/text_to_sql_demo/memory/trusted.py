from __future__ import annotations

from text_to_sql_demo.metadata.models import SavedQueryRecord
from text_to_sql_demo.metadata.store import MetadataStore
from text_to_sql_demo.retrieval.knowledge import (
    KnowledgeSearchHit,
    KnowledgeStore,
    ReferenceSqlItem,
)

TRUSTED_SAVED_QUERY_CANDIDATE_LIMIT = 50


def search_approved_saved_query_reference_sql(
    *,
    metadata_store: MetadataStore | None,
    query: str,
    involved_tables: list[str],
    top_k: int,
) -> list[KnowledgeSearchHit[ReferenceSqlItem]]:
    """从 approved saved_query 中检索可注入 prompt 的可信 Reference SQL。"""
    if metadata_store is None or top_k <= 0:
        return []

    candidate_limit = min(TRUSTED_SAVED_QUERY_CANDIDATE_LIMIT, max(top_k * 5, top_k))
    saved_queries = metadata_store.list_saved_queries(
        status="approved",
        limit=candidate_limit,
    ).items
    if not saved_queries:
        return []

    store = KnowledgeStore(
        reference_sql=[
            _saved_query_to_reference_sql(saved_query)
            for saved_query in saved_queries
        ]
    )
    return store.search(
        query=query,
        involved_tables=involved_tables,
        top_k=top_k,
    ).reference_sql


def merge_reference_sql_hits(
    *,
    yaml_hits: list[KnowledgeSearchHit[ReferenceSqlItem]],
    trusted_hits: list[KnowledgeSearchHit[ReferenceSqlItem]],
    top_k: int,
) -> list[KnowledgeSearchHit[ReferenceSqlItem]]:
    """合并 YAML 与可信 saved_query 命中，并按 name/sql 去重后裁剪 Top-K。"""
    if top_k <= 0:
        return []

    merged: list[KnowledgeSearchHit[ReferenceSqlItem]] = []
    seen_names: set[str] = set()
    seen_sql: set[str] = set()
    combined = sorted(
        [*yaml_hits, *trusted_hits],
        key=lambda hit: (-hit.score, hit.item.name, hit.item.sql),
    )
    for hit in combined:
        name_key = hit.item.name.strip().lower()
        sql_key = " ".join(hit.item.sql.split()).lower()
        if name_key in seen_names or sql_key in seen_sql:
            continue
        merged.append(hit)
        seen_names.add(name_key)
        seen_sql.add(sql_key)
        if len(merged) >= top_k:
            break
    return merged


def _saved_query_to_reference_sql(saved_query: SavedQueryRecord) -> ReferenceSqlItem:
    """把数据团队审核后的 saved_query 映射成可信 Reference SQL 条目。"""
    return ReferenceSqlItem(
        name=saved_query.name,
        natural_language=saved_query.question,
        sql=saved_query.sql,
        tags=list(saved_query.tags),
        involved_tables=[],
    )
