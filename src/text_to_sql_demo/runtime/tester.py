from __future__ import annotations

from typing import Any

from text_to_sql_demo.llm.client import LLMClient
from text_to_sql_demo.runtime.exceptions import RuntimeConnectionTestError
from text_to_sql_demo.schema.catalog import read_schema_metadata


class RuntimeConfigTester:
    """运行时数据库与模型连通性测试服务。"""

    def test_database(self, database_url: str) -> dict[str, Any]:
        """读取 Schema 元数据，并返回脱敏后的概要信息。"""
        try:
            schema = read_schema_metadata(database_url)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeConnectionTestError("运行时数据库连接测试失败") from exc

        column_count = sum(len(table.columns) for table in schema.tables.values())
        return {
            "success": True,
            "table_count": len(schema.tables),
            "column_count": column_count,
            "tables": sorted(schema.tables),
        }

    def test_model(
        self,
        *,
        client: LLMClient,
        model_alias: str,
        model_name: str,
    ) -> dict[str, Any]:
        """发送极小 prompt，验证模型 client 可调用。"""
        try:
            response = client.complete(
                model_alias=model_alias,
                model_name=model_name,
                system_prompt="只返回 ok。",
                user_prompt="ok",
                temperature=0.0,
                max_tokens=8,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeConnectionTestError("运行时模型连接测试失败") from exc

        return {
            "success": True,
            "model_alias": response.model_alias,
            "model": model_name,
            "provider": response.provider_name,
        }
