from pathlib import Path

import pytest

from evaluation.code_freeze import (
    controlled_code_sha256,
    evaluation_baseline_id,
)


def _controlled_tree(root: Path, *, reverse: bool = False) -> None:
    files = (
        ("app/service.py", "SERVICE = 1\n"),
        ("evaluation/runner.py", "RUNNER = 1\n"),
        ("tools/__init__.py", ""),
        ("tools/freeze_view_semantics.py", "FREEZE = 1\n"),
        ("tools/run_pagila_evaluation.py", "EVALUATE = 1\n"),
        ("pyproject.toml", "[project]\nname = 'synthetic'\n"),
    )
    for relative, content in reversed(files) if reverse else files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_controlled_code_hash_is_stable_across_creation_order(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _controlled_tree(first)
    _controlled_tree(second, reverse=True)

    assert controlled_code_sha256(first) == controlled_code_sha256(
        second
    )


@pytest.mark.parametrize(
    "relative",
    [
        "app/service.py",
        "evaluation/runner.py",
        "tools/__init__.py",
        "tools/freeze_view_semantics.py",
        "tools/run_pagila_evaluation.py",
        "pyproject.toml",
    ],
)
def test_any_controlled_source_change_changes_digest(
    tmp_path: Path,
    relative: str,
) -> None:
    _controlled_tree(tmp_path)
    original = controlled_code_sha256(tmp_path)
    (tmp_path / relative).write_text("CHANGED = 1\n", encoding="utf-8")

    assert controlled_code_sha256(tmp_path) != original


def test_mutable_artifacts_do_not_enter_code_digest(
    tmp_path: Path,
) -> None:
    _controlled_tree(tmp_path)
    original = controlled_code_sha256(tmp_path)
    ignored = {
        ".env": "LLM_API_KEY=secret\n",
        "evaluation/reports/run.json": '{"passed": false}\n',
        "evaluation/__pycache__/runner.py": "cache\n",
        "evaluation/cases/pagila_mvp.jsonl": (
            '{"case_id":"PG-MVP-001","status":"verified"}\n'
        ),
    }
    for relative, content in ignored.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    assert controlled_code_sha256(tmp_path) == original


def test_controlled_code_hash_rejects_missing_or_symlinked_sources(
    tmp_path: Path,
) -> None:
    _controlled_tree(tmp_path)
    (tmp_path / "tools/run_pagila_evaluation.py").unlink()
    with pytest.raises(ValueError, match="controlled code"):
        controlled_code_sha256(tmp_path)

    _controlled_tree(tmp_path)
    target = tmp_path / "outside.py"
    target.write_text("OUTSIDE = 1\n", encoding="utf-8")
    link = tmp_path / "app/link.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(ValueError, match="controlled code"):
        controlled_code_sha256(tmp_path)


def test_evaluation_baseline_id_is_canonical_and_drift_sensitive() -> None:
    first = {
        "prompt_version": "prompt-v1",
        "semantic": {
            "manifest_sha256": "1" * 64,
            "schema_version": "2" * 64,
        },
    }
    reordered = {
        "semantic": {
            "schema_version": "2" * 64,
            "manifest_sha256": "1" * 64,
        },
        "prompt_version": "prompt-v1",
    }

    baseline_id = evaluation_baseline_id(first)

    assert baseline_id == evaluation_baseline_id(reordered)
    assert baseline_id != evaluation_baseline_id(
        {**first, "prompt_version": "prompt-v2"}
    )
