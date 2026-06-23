from typing import Any

from pydantic import BaseModel, Field


class PromptBuildResult(BaseModel):
    """PromptBuilder 输出。"""

    system_prompt: str
    user_prompt: str
    summary: dict[str, Any] = Field(default_factory=dict)


class PromptBuilder:
    """只使用 linked schema 和 Top-K 示例构建 SQL 生成 prompt。"""

    def build(
        self,
        *,
        user_question: str,
        target_dialect: str,
        linked_schema: dict,
        examples: list[dict],
        original_schema: dict | None = None,
        original_example_count: int | None = None,
    ) -> PromptBuildResult:
        tables = linked_schema.get("tables", [])
        schema_lines = []
        column_count = 0
        for table in tables:
            table_name = table.get("name")
            columns = table.get("columns", {})
            schema_lines.append(f"- table {table_name}")
            for column in columns.values():
                column_count += 1
                schema_lines.append(f"  - {column.get('name')} {column.get('type')}")

        example_lines = []
        for index, item in enumerate(examples, start=1):
            example = item.get("example", item)
            example_lines.extend(
                [
                    f"Example {index} question: {example.get('natural_language')}",
                    f"Example {index} SQL: {example.get('sql')}",
                ]
            )

        user_prompt = "\n".join(
            [
                f"User question: {user_question}",
                f"Target dialect: {target_dialect}",
                "Linked schema:",
                *schema_lines,
                "Top-K examples:",
                *example_lines,
                "SQL output constraints:",
                "- Return exactly one SQL query.",
                "- Return only SQL text without explanations.",
                "- Do not wrap output in code fences.",
                "- Use only the linked schema shown above.",
            ]
        )
        injected_table_count = len(tables)
        injected_example_count = len(examples)
        original_schema_table_count = _count_schema_tables(original_schema or linked_schema)
        resolved_original_example_count = (
            original_example_count
            if original_example_count is not None
            else injected_example_count
        )
        return PromptBuildResult(
            system_prompt="You are a Text-to-SQL generator.",
            user_prompt=user_prompt,
            summary={
                "target_dialect": target_dialect,
                "linked_table_count": injected_table_count,
                "linked_column_count": column_count,
                "example_count": injected_example_count,
                "original_schema_table_count": original_schema_table_count,
                "injected_schema_table_count": injected_table_count,
                "original_example_count": resolved_original_example_count,
                "injected_example_count": injected_example_count,
            },
        )


def _count_schema_tables(schema: dict) -> int:
    tables = schema.get("tables") if isinstance(schema, dict) else None
    if isinstance(tables, dict | list):
        return len(tables)
    return 0
