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
                    "term": {"type": "string", "required": False},
                    "raw_query": {"type": "string", "required": False},
                    "repo": {"type": "string", "required": False},
                    "expand_variants": {"type": "boolean", "required": False, "default": False},
                    "context_lines": {"type": "integer", "required": False, "default": 5, "minimum": 0, "maximum": 10},
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

    with pytest.raises(ValueError, match="must be <= 10"):
        runner.parse_workflow_cli_command('symbol_usage --term "ProcessOrder" --context-lines 11')


def test_parse_workflow_cli_accepts_integer_within_bounds(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command(
        'symbol_usage --term "ProcessOrder" --repo "github.com/acme/ui" --context-lines 10'
    )

    assert workflow_id == "symbol_usage"
    assert args["term"] == "ProcessOrder"
    assert args["repo"] == "github.com/acme/ui"
    assert args["context_lines"] == 10


def test_parse_workflow_cli_applies_default_and_keeps_it_bounded(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command('symbol_usage --term "ProcessOrder"')

    assert workflow_id == "symbol_usage"
    assert args["context_lines"] == 5
    assert args["expand_variants"] is False


def test_parse_workflow_cli_normalizes_over_escaped_double_quotes(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command(
        'symbol_usage --raw-query \\"addToPantry r:github.com/acme/ui\\" --context-lines 1'
    )

    assert workflow_id == "symbol_usage"
    assert args["raw_query"] == "addToPantry r:github.com/acme/ui"
    assert args["context_lines"] == 1


def test_parse_workflow_cli_adds_hint_for_split_value_from_over_escaped_quotes(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    with pytest.raises(ValueError, match="over-escaped quotes"):
        runner.parse_workflow_cli_command('symbol_usage --raw-query \\"addToPantry r:github.com/acme/ui --context-lines 1')


def test_build_cli_argv_tokens_normalizes_flags_and_values() -> None:
    argv = ExecutionRunner._build_cli_argv_tokens(
        {
            "expand_variants": False,
            "context_lines": 1,
            "raw_query": "addToPantry r:github.com/acme/ui",
        }
    )

    assert "--expand-variants" in argv
    assert "--context-lines" in argv
    assert "--raw-query" in argv
    assert "false" in argv
    assert "1" in argv
    assert "addToPantry r:github.com/acme/ui" in argv


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
