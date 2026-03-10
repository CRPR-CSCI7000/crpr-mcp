import asyncio
from pathlib import Path

import pytest
import yaml

from execution.runner import ExecutionRunner


def _write_manifest(path: Path) -> None:
    manifest = {
        "workflows": [
            {
                "id": "symbol_usage",
                "script_path": "workflows/scripts/symbol_usage.py",
                "arg_schema": {
                    "query": {"type": "string", "required": True},
                    "context_lines": {"type": "integer", "required": False, "default": 2, "minimum": 0, "maximum": 2},
                },
            }
        ]
    }
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")


def _build_runner(tmp_path: Path) -> ExecutionRunner:
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path)
    return ExecutionRunner(
        src_root=tmp_path,
        manifest_path=manifest_path,
        timeout_default=30,
        timeout_max=120,
        stdout_max_bytes=32768,
        stderr_max_bytes=32768,
    )


def test_parse_workflow_cli_rejects_integer_above_maximum(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    with pytest.raises(ValueError, match="must be <= 2"):
        runner.parse_workflow_cli_command('symbol_usage --query "ProcessOrder" --context-lines 3')


def test_parse_workflow_cli_accepts_integer_within_bounds(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command('symbol_usage --query "ProcessOrder" --context-lines 2')

    assert workflow_id == "symbol_usage"
    assert args["query"] == "ProcessOrder"
    assert args["context_lines"] == 2


def test_parse_workflow_cli_applies_default_and_keeps_it_bounded(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command('symbol_usage --query "ProcessOrder"')

    assert workflow_id == "symbol_usage"
    assert args["context_lines"] == 2


def test_parse_workflow_cli_normalizes_over_escaped_double_quotes(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command(
        'symbol_usage --query \\"ProcessOrder r:checkout\\" --context-lines 1'
    )

    assert workflow_id == "symbol_usage"
    assert args["query"] == "ProcessOrder r:checkout"
    assert args["context_lines"] == 1


def test_parse_workflow_cli_adds_hint_for_split_value_from_over_escaped_quotes(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    with pytest.raises(ValueError, match="over-escaped quotes"):
        runner.parse_workflow_cli_command('symbol_usage --query \\"ProcessOrder r:checkout --context-lines 1')


def test_build_cli_argv_tokens_normalizes_flags_and_values() -> None:
    argv = ExecutionRunner._build_cli_argv_tokens(
        {
            "include_source_repo": False,
            "max_repos": 5,
            "query": "ProcessOrder",
        }
    )

    assert "--include-source-repo" in argv
    assert "--max-repos" in argv
    assert "--query" in argv
    assert "false" in argv
    assert "5" in argv
    assert "ProcessOrder" in argv


def test_run_custom_workflow_code_accepts_plain_text_stdout() -> None:
    project_root = Path(__file__).resolve().parents[1]
    runner = ExecutionRunner(
        src_root=project_root / "src",
        manifest_path=project_root / "src" / "workflows" / "manifest.yaml",
        timeout_default=30,
        timeout_max=120,
        stdout_max_bytes=32768,
        stderr_max_bytes=32768,
    )

    result = asyncio.run(runner.run_custom_workflow_code(code="print('hello world')", timeout_seconds=30))

    assert result.success is True
    assert result.result_json == "hello world"
    assert "result marker not found" not in (result.stderr or "").lower()


def test_run_custom_workflow_code_accepts_plain_json_stdout() -> None:
    project_root = Path(__file__).resolve().parents[1]
    runner = ExecutionRunner(
        src_root=project_root / "src",
        manifest_path=project_root / "src" / "workflows" / "manifest.yaml",
        timeout_default=30,
        timeout_max=120,
        stdout_max_bytes=32768,
        stderr_max_bytes=32768,
    )

    result = asyncio.run(
        runner.run_custom_workflow_code(
            code="import json\nprint(json.dumps({'ok': True, 'count': 2}, ensure_ascii=True))",
            timeout_seconds=30,
        )
    )

    assert result.success is True
    assert result.result_json == {"ok": True, "count": 2}
