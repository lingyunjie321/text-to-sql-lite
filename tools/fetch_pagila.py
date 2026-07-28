from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_EXPECTED_FILES = ("pagila-schema.sql", "pagila-data.sql")
_REQUIRED_KEYS = {
    "source",
    "tag",
    "commit",
    "archive_url",
    "archive_sha256",
    "files",
}


@dataclass(frozen=True, slots=True)
class PagilaFiles:
    schema: Path
    data: Path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if set(manifest) < _REQUIRED_KEYS:
        raise ValueError("Pagila manifest is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_EXPECTED_FILES):
        raise ValueError("Pagila manifest is invalid")
    for name in _EXPECTED_FILES:
        entry = files.get(name)
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("member"), str)
            or not isinstance(entry.get("sha256"), str)
        ):
            raise ValueError("Pagila manifest is invalid")
    for key in (
        "source",
        "tag",
        "commit",
        "archive_url",
        "archive_sha256",
    ):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError("Pagila manifest is invalid")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Pagila manifest is invalid") from error
    if not isinstance(manifest, dict):
        raise ValueError("Pagila manifest is invalid")
    _validate_manifest(manifest)
    return manifest


def _existing_files(
    target_dir: Path, manifest: dict[str, Any]
) -> PagilaFiles | None:
    schema = target_dir / _EXPECTED_FILES[0]
    data = target_dir / _EXPECTED_FILES[1]
    if not schema.is_file() or not data.is_file():
        return None
    files = manifest["files"]
    if (
        _sha256_file(schema) == files[schema.name]["sha256"]
        and _sha256_file(data) == files[data.name]["sha256"]
    ):
        return PagilaFiles(schema=schema, data=data)
    return None


def extract_verified_archive(
    archive_path: Path,
    target_dir: Path,
    manifest: dict[str, Any],
) -> PagilaFiles:
    _validate_manifest(manifest)
    target_dir.mkdir(parents=True, exist_ok=True)
    existing = _existing_files(target_dir, manifest)
    if existing is not None:
        return existing
    if _sha256_file(archive_path) != manifest["archive_sha256"]:
        raise ValueError("Pagila archive verification failed")

    contents: dict[str, bytes] = {}
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for name in _EXPECTED_FILES:
                entry = manifest["files"][name]
                try:
                    member = archive.getmember(entry["member"])
                except KeyError as error:
                    raise ValueError(
                        "Pagila member verification failed"
                    ) from error
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Pagila member verification failed")
                content = stream.read()
                if _sha256_bytes(content) != entry["sha256"]:
                    raise ValueError("Pagila member verification failed")
                contents[name] = content
    except (tarfile.TarError, OSError) as error:
        raise ValueError("Pagila archive verification failed") from error

    temporary_paths: list[Path] = []
    try:
        for name in _EXPECTED_FILES:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target_dir,
                prefix=f".{name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(contents[name])
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_paths.append(Path(temporary.name))
        for name, temporary_path in zip(_EXPECTED_FILES, temporary_paths):
            temporary_path.replace(target_dir / name)
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)

    return PagilaFiles(
        schema=target_dir / _EXPECTED_FILES[0],
        data=target_dir / _EXPECTED_FILES[1],
    )


def fetch_pagila(manifest_path: Path, target_dir: Path) -> PagilaFiles:
    manifest = load_manifest(manifest_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    existing = _existing_files(target_dir, manifest)
    if existing is not None:
        return existing

    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target_dir,
        prefix=".pagila-archive.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        archive_path = Path(temporary.name)
        try:
            with urllib.request.urlopen(manifest["archive_url"]) as response:
                while chunk := response.read(1024 * 1024):
                    temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

    try:
        return extract_verified_archive(archive_path, target_dir, manifest)
    finally:
        archive_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and verify the locked Pagila fixture."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    files = fetch_pagila(args.manifest, args.output)
    print(
        f"Verified {manifest['tag']} ({manifest['commit']}) from "
        f"{manifest['source']} into {files.schema.parent}"
    )


if __name__ == "__main__":
    main()
