import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from tools.fetch_pagila import (
    extract_verified_archive,
    load_manifest,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_archive(
    path: Path,
    *,
    prefix: str,
    schema: bytes | None,
    data: bytes | None,
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in (
            ("pagila-schema.sql", schema),
            ("pagila-data.sql", data),
        ):
            if content is None:
                continue
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def _manifest(archive: Path, schema: bytes, data: bytes) -> dict[str, object]:
    prefix = "pagila-locked"
    return {
        "source": "https://example.invalid/pagila",
        "tag": "locked",
        "commit": "locked",
        "archive_url": "https://example.invalid/pagila.tar.gz",
        "archive_sha256": _sha256(archive.read_bytes()),
        "files": {
            "pagila-schema.sql": {
                "member": f"{prefix}/pagila-schema.sql",
                "sha256": _sha256(schema),
            },
            "pagila-data.sql": {
                "member": f"{prefix}/pagila-data.sql",
                "sha256": _sha256(data),
            },
        },
    }


def test_extract_verified_archive_writes_both_files_atomically(
    tmp_path: Path,
) -> None:
    schema = b"CREATE TABLE film (film_id integer);"
    data = b"INSERT INTO film VALUES (1);"
    archive = tmp_path / "pagila.tar.gz"
    _write_archive(
        archive, prefix="pagila-locked", schema=schema, data=data
    )

    outputs = extract_verified_archive(
        archive, tmp_path / "output", _manifest(archive, schema, data)
    )

    assert outputs.schema.read_bytes() == schema
    assert outputs.data.read_bytes() == data
    assert not list((tmp_path / "output").glob("*.tmp"))


@pytest.mark.parametrize("failure", ["archive", "schema", "missing"])
def test_extract_verified_archive_writes_nothing_on_verification_failure(
    tmp_path: Path, failure: str
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "pagila.tar.gz"
    _write_archive(
        archive,
        prefix="pagila-locked",
        schema=schema,
        data=None if failure == "missing" else data,
    )
    manifest = _manifest(archive, schema, data)
    if failure == "archive":
        manifest["archive_sha256"] = "0" * 64
    elif failure == "schema":
        manifest["files"]["pagila-schema.sql"]["sha256"] = "0" * 64  # type: ignore[index]

    output = tmp_path / "output"
    with pytest.raises(ValueError, match="verification failed"):
        extract_verified_archive(archive, output, manifest)

    assert not list(output.glob("*.sql"))
    assert not list(output.glob("*.tmp"))


def test_extract_verified_archive_replaces_corrupt_existing_files(
    tmp_path: Path,
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "pagila.tar.gz"
    _write_archive(
        archive, prefix="pagila-locked", schema=schema, data=data
    )
    output = tmp_path / "output"
    output.mkdir()
    (output / "pagila-schema.sql").write_bytes(b"corrupt")
    (output / "pagila-data.sql").write_bytes(b"corrupt")

    files = extract_verified_archive(
        archive, output, _manifest(archive, schema, data)
    )

    assert files.schema.read_bytes() == schema
    assert files.data.read_bytes() == data


def test_extract_verified_archive_reuses_valid_existing_files(
    tmp_path: Path,
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "pagila.tar.gz"
    _write_archive(
        archive, prefix="pagila-locked", schema=schema, data=data
    )
    manifest = _manifest(archive, schema, data)
    archive.unlink()
    output = tmp_path / "output"
    output.mkdir()
    schema_path = output / "pagila-schema.sql"
    data_path = output / "pagila-data.sql"
    schema_path.write_bytes(schema)
    data_path.write_bytes(data)

    files = extract_verified_archive(archive, output, manifest)

    assert files.schema == schema_path
    assert files.data == data_path


def test_failed_verification_preserves_existing_corrupt_files(
    tmp_path: Path,
) -> None:
    schema = b"schema"
    data = b"data"
    archive = tmp_path / "pagila.tar.gz"
    _write_archive(
        archive, prefix="pagila-locked", schema=schema, data=data
    )
    manifest = _manifest(archive, schema, data)
    manifest["archive_sha256"] = "0" * 64
    output = tmp_path / "output"
    output.mkdir()
    schema_path = output / "pagila-schema.sql"
    data_path = output / "pagila-data.sql"
    schema_path.write_bytes(b"old-schema")
    data_path.write_bytes(b"old-data")

    with pytest.raises(ValueError, match="verification failed"):
        extract_verified_archive(archive, output, manifest)

    assert schema_path.read_bytes() == b"old-schema"
    assert data_path.read_bytes() == b"old-data"


def test_load_manifest_rejects_missing_required_keys(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"source": "missing"}), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest is invalid"):
        load_manifest(manifest)
