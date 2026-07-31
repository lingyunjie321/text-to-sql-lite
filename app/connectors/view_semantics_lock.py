"""视图语义清单的冻结锁定常量。

记录当前冻结的视图语义清单路径及其 SHA-256 摘要、Pagila 数据库
结构摘要，用于在加载清单时校验内容未被篡改（代码冻结契约的一部分）。
"""

from pathlib import Path

VIEW_SEMANTIC_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "pagila"
    / "view_semantics.json"
)
VIEW_SEMANTIC_MANIFEST_SHA256 = (
    "4f91262d600de09c42b38a0cbef7e0c7f9b6f724c9bd4b9c8fa27a625e61673f"
)
PAGILA_DATABASE_SCHEMA_SHA256 = (
    "74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2"
)
