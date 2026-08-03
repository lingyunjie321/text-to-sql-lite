import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from tools.fetch_sakila import extract_verified_archive, load_manifest

_ROOT = Path(__file__).parents[2]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_archive(
    path: Path,
    *,
    schema: bytes | None,
    data: bytes | None,
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in (
            ("sakila-schema.sql", schema),
            ("sakila-data.sql", data),
        ):
            if content is None:
                continue
            info = tarfile.TarInfo(f"sakila-db/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def _manifest(
    archive: Path,
    schema: bytes,
    data: bytes,
) -> dict[str, object]:
    return {
        "source": "https://dev.mysql.com/doc/index-other.html",
        "sakila_version": "1.5",
        "archive_url": "https://example.invalid/sakila-db.tar.gz",
        "archive_sha256": _sha256(archive.read_bytes()),
        "retrieved_at": "2026-08-03",
        "files": {
            "sakila-schema.sql": {
                "member": "sakila-db/sakila-schema.sql",
                "sha256": _sha256(schema),
            },
            "sakila-data.sql": {
                "member": "sakila-db/sakila-data.sql",
                "sha256": _sha256(data),
            },
        },
    }


def test_extract_verified_archive_writes_locked_sakila_files(
    tmp_path: Path,
) -> None:
    schema = b"CREATE DATABASE sakila;"
    data = b"INSERT INTO actor VALUES (1);"
    archive = tmp_path / "sakila-db.tar.gz"
    _write_archive(archive, schema=schema, data=data)

    files = extract_verified_archive(
        archive,
        tmp_path / "output",
        _manifest(archive, schema, data),
    )

    assert files.schema.read_bytes() == schema
    assert files.data.read_bytes() == data
    assert not list((tmp_path / "output").glob("*.tmp"))


@pytest.mark.parametrize("failure", ["archive", "schema", "missing"])
def test_extract_verified_archive_rejects_untrusted_sakila(
    tmp_path: Path,
    failure: str,
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "sakila-db.tar.gz"
    _write_archive(
        archive,
        schema=schema,
        data=None if failure == "missing" else data,
    )
    manifest = _manifest(archive, schema, data)
    if failure == "archive":
        manifest["archive_sha256"] = "0" * 64
    elif failure == "schema":
        manifest["files"]["sakila-schema.sql"]["sha256"] = "0" * 64  # type: ignore[index]

    output = tmp_path / "output"
    with pytest.raises(ValueError, match="verification failed"):
        extract_verified_archive(archive, output, manifest)

    assert not list(output.glob("*.sql"))


def test_load_manifest_rejects_missing_trust_anchor(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"source": "missing"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest is invalid"):
        load_manifest(manifest)


def test_load_manifest_requires_explicit_sakila_version(
    tmp_path: Path,
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "sakila-db.tar.gz"
    _write_archive(archive, schema=schema, data=data)
    payload = _manifest(archive, schema, data)
    del payload["sakila_version"]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest is invalid"):
        load_manifest(manifest)


def test_load_manifest_rejects_archive_member_path_traversal(
    tmp_path: Path,
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "sakila-db.tar.gz"
    _write_archive(archive, schema=schema, data=data)
    payload = _manifest(archive, schema, data)
    payload["files"]["sakila-schema.sql"]["member"] = (  # type: ignore[index]
        "../sakila-schema.sql"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest is invalid"):
        load_manifest(manifest)


def test_extract_verified_archive_reuses_verified_existing_files(
    tmp_path: Path,
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "sakila-db.tar.gz"
    _write_archive(archive, schema=schema, data=data)
    manifest = _manifest(archive, schema, data)
    output = tmp_path / "output"
    output.mkdir()
    (output / "sakila-schema.sql").write_bytes(schema)
    (output / "sakila-data.sql").write_bytes(data)
    archive.unlink()

    files = extract_verified_archive(archive, output, manifest)

    assert files.schema.read_bytes() == schema
    assert files.data.read_bytes() == data


def test_mysql_compose_locks_image_and_mounts_verified_fixture() -> None:
    compose = (
        _ROOT / "infrastructure/mysql/compose.yaml"
    ).read_text(encoding="utf-8")

    assert (
        "mysql:8.4.10@sha256:"
        "8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6"
    ) in compose
    assert "sakila-schema.sql:/docker-entrypoint-initdb.d/01-" in compose
    assert "sakila-data.sql:/docker-entrypoint-initdb.d/02-" in compose
    assert "03-create-readonly-user.sh:/docker-entrypoint-initdb.d/03-" in compose
    assert "MYSQL_USER: text_to_sql_reader" in compose
    assert '"127.0.0.1:${MYSQL_HOST_PORT:-53306}:3306"' in compose


def test_mysql_init_revokes_write_access_and_grants_only_structure_reads(
) -> None:
    script = (
        _ROOT
        / "infrastructure/mysql/init/03-create-readonly-user.sh"
    ).read_text(encoding="utf-8")

    assert "REVOKE ALL PRIVILEGES, GRANT OPTION" in script
    assert "GRANT SELECT, SHOW VIEW ON sakila.*" in script
    for forbidden in ("GRANT INSERT", "GRANT UPDATE", "GRANT DELETE"):
        assert forbidden not in script
