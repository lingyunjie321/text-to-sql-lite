from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

_CONTROLLED_DIRECTORIES = ("app", "evaluation")
_CONTROLLED_FILES = (
    "pyproject.toml",
    "tools/__init__.py",
    "tools/freeze_view_semantics.py",
    "tools/run_pagila_evaluation.py",
)
_EXCLUDED_DIRECTORIES = frozenset({"__pycache__", "reports"})


def _controlled_paths(root: Path) -> tuple[Path, ...]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("controlled code tree is invalid")
    paths: list[Path] = []
    try:
        for relative in _CONTROLLED_DIRECTORIES:
            directory = root / relative
            if not directory.is_dir() or directory.is_symlink():
                raise ValueError("controlled code tree is invalid")
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise ValueError("controlled code tree is invalid")
                local_parts = path.relative_to(directory).parts
                if any(
                    part in _EXCLUDED_DIRECTORIES
                    for part in local_parts
                ):
                    continue
                if path.is_file() and path.suffix == ".py":
                    paths.append(path)
        for relative in _CONTROLLED_FILES:
            path = root / relative
            if (
                not path.is_file()
                or path.is_symlink()
                or path.suffix not in {".py", ".toml"}
            ):
                raise ValueError("controlled code tree is invalid")
            paths.append(path)
    except OSError:
        raise ValueError("controlled code tree is invalid") from None
    return tuple(
        sorted(
            set(paths),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def controlled_code_sha256(root: Path) -> str:
    paths = _controlled_paths(root)
    digest = hashlib.sha256()
    domain = b"stage10-controlled-code-v1"
    digest.update(len(domain).to_bytes(4, "big"))
    digest.update(domain)
    digest.update(len(paths).to_bytes(8, "big"))
    try:
        for path in paths:
            if path.is_symlink():
                raise OSError
            relative = path.relative_to(root).as_posix().encode("utf-8")
            content = path.read_bytes()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
    except (OSError, UnicodeEncodeError, ValueError):
        raise ValueError("controlled code tree is invalid") from None
    return digest.hexdigest()


def evaluation_baseline_id(payload: Mapping[str, object]) -> str:
    if "evaluation_baseline_id" in payload:
        raise ValueError("evaluation baseline payload is invalid")
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ValueError(
            "evaluation baseline payload is invalid"
        ) from None
    domain = b"stage10-evaluation-baseline-v1"
    framed = (
        len(domain).to_bytes(4, "big")
        + domain
        + len(encoded).to_bytes(8, "big")
        + encoded
    )
    return hashlib.sha256(framed).hexdigest()
