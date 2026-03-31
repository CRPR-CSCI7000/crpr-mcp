from pathlib import Path

from src.execution.models import ExecutionResult
from src.execution.runner import (
    _TRACKING_FILE_ENV,
    _TRACKING_RUN_ID_ENV,
    _TRACKING_WORKFLOW_ID_ENV,
    ExecutionRunner,
)
from src.skills.workflows.renderers import format_workflow_result_markdown


def _write_skill(skills_root: Path) -> None:
    capability_path = skills_root / "capabilities" / "repo_discovery.md"
    script_path = skills_root / "workflows" / "scripts" / "repo_discovery.py"
    capability_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    capability_path.write_text(
        """---
id: repo_discovery
doc_type: capability
kind: workflow
order: 1
execution:
  script_path: skills/workflows/scripts/repo_discovery.py
  arg_schema: {}
---

--- list_capabilities ---
- Summary: test
- When to use: test

--- read_capability ---
## test
### Expected Output Summary
Returns a JSON object with:
{{EXPECTED_OUTPUT_SUMMARY}}
""",
        encoding="utf-8",
    )
    script_path.write_text(
        "from pydantic import BaseModel\n\n\nclass OutputModel(BaseModel):\n    ok: bool = True\n",
        encoding="utf-8",
    )


def _build_runner(tmp_path: Path) -> ExecutionRunner:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root)
    return ExecutionRunner(
        src_root=tmp_path,
        skills_root=skills_root,
        timeout_default=30,
        timeout_max=120,
        stdout_max_bytes=32768,
        stderr_max_bytes=32768,
    )


def test_build_environment_includes_tracking_vars_when_passed(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)
    env = runner._build_environment(
        github_rpc_url="http://127.0.0.1:9999/internal/github-rpc",
        extra_env={
            _TRACKING_FILE_ENV: "D:/tmp/track.jsonl",
            _TRACKING_RUN_ID_ENV: "abc123",
            _TRACKING_WORKFLOW_ID_ENV: "symbol_usage",
        },
    )

    assert env[_TRACKING_FILE_ENV] == "D:/tmp/track.jsonl"
    assert env[_TRACKING_RUN_ID_ENV] == "abc123"
    assert env[_TRACKING_WORKFLOW_ID_ENV] == "symbol_usage"


def test_attach_tracking_summary_reads_events_and_merges_result_json(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)
    tracking_file = tmp_path / "runtime_tracking.jsonl"
    tracking_file.write_text(
        (
            '{"event_type":"runtime_call","system":"zoekt","operation":"search","is_query":true}\n'
            '{"event_type":"runtime_call","system":"github","operation":"get_pull_request","is_query":true}\n'
        ),
        encoding="utf-8",
    )
    result = ExecutionResult(success=True, exit_code=0, result_json={"mode": "structured"}, timing_ms=7850)

    merged = runner._attach_tracking_summary(
        result=result,
        workflow_id="symbol_usage",
        tracking_run_id="run-123",
        tracking_path=tracking_file,
    )

    assert isinstance(merged.result_json, dict)
    tracking = merged.result_json["_crpr_run_tracking"]
    assert tracking["tracking_run_id"] == "run-123"
    assert tracking["workflow_id"] == "symbol_usage"
    assert tracking["total_runtime_calls"] == 2
    assert tracking["zoekt_or_github_queries_made"] == 2
    assert tracking["query_breakdown"]["zoekt"] == 1
    assert tracking["query_breakdown"]["github"] == 1
    assert tracking["total_latency_seconds"] == 7.85


def test_renderer_prints_tracking_section_and_hidden_marker() -> None:
    result = ExecutionResult(
        success=True,
        exit_code=0,
        result_json={
            "mode": "structured",
            "total_queries": 1,
            "total_raw_hits": 2,
            "total_hits": 2,
            "results": [],
            "_crpr_run_tracking": {
                "tracking_run_id": "track-1",
                "workflow_id": "symbol_usage",
                "total_runtime_calls": 2,
                "zoekt_or_github_queries_made": 2,
                "query_breakdown": {"zoekt": 1, "github": 1},
                "total_latency_seconds": 1.234,
            },
        },
    )

    markdown = format_workflow_result_markdown("symbol_usage", result)

    assert "### Run Tracking" in markdown
    assert "Tracking run ID: `track-1`" in markdown
    assert "<!--CRPR_RUN_TRACKING:" in markdown
