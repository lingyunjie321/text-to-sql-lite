from text_to_sql_demo.schema import catalog


class FakeEngine:
    """用于避免单元测试连接真实数据库。"""

    def dispose(self) -> None:
        pass


class FakeInspector:
    """返回空 schema，测试只关注连接串脱敏。"""

    def get_table_names(self) -> list[str]:
        return []


def test_read_schema_metadata_redacts_database_password(monkeypatch) -> None:
    raw_url = "postgresql+psycopg://readonly:secret@db.example.com:5432/app"

    monkeypatch.setattr(catalog, "create_engine", lambda database_url: FakeEngine())
    monkeypatch.setattr(catalog, "inspect", lambda engine: FakeInspector())

    metadata = catalog.read_schema_metadata(raw_url)

    assert metadata.database_url == "postgresql+psycopg://readonly:***@db.example.com:5432/app"
    assert "secret" not in metadata.model_dump_json()
