import asyncio
from pathlib import Path

import pytest

from src.execution.models import ExecutionResult
from src.execution.runner import ExecutionRunner


def _write_skill(skills_root: Path) -> None:
    skill_path = skills_root / "capabilities" / "symbol_usage.md"
    script_path = skills_root / "workflows" / "scripts" / "symbol_usage.py"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        """---
id: symbol_usage
doc_type: capability
kind: workflow
order: 1
execution:
  script_path: skills/workflows/scripts/symbol_usage.py
  arg_schema:
    term:
      type: string
      required: false
    repo:
      type: string
      required: false
    expand_variants:
      type: boolean
      required: false
      default: false
    context_lines:
      type: integer
      required: false
      default: 5
      minimum: 0
      maximum: 10
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
        """from pydantic import BaseModel


class OutputModel(BaseModel):
    mode: str
""",
        encoding="utf-8",
    )


def _write_cross_repo_grep_skill(skills_root: Path) -> None:
    skill_path = skills_root / "capabilities" / "cross_repo_grep.md"
    script_path = skills_root / "workflows" / "scripts" / "cross_repo_grep.py"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        """---
id: cross_repo_grep
doc_type: capability
kind: workflow
order: 1
execution:
  script_path: skills/workflows/scripts/cross_repo_grep.py
  arg_schema:
    regexp:
      type: string
      required: true
      position: 1
      aliases: ["-e", "--regexp"]
    path:
      type: string
      required: true
      position: 2
    ignore_case:
      type: boolean
      required: false
      default: false
      aliases: ["-i"]
    line_number:
      type: boolean
      required: false
      default: false
      aliases: ["-n"]
    context_lines:
      type: integer
      required: false
      default: 0
      minimum: 0
      maximum: 50
      aliases: ["-C"]
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
        """from pydantic import BaseModel


class OutputModel(BaseModel):
    ok: bool
""",
        encoding="utf-8",
    )


def _build_runner(tmp_path: Path) -> ExecutionRunner:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "__init__.py").write_text("", encoding="utf-8")
    return ExecutionRunner(
        src_root=tmp_path,
        skills_root=skills_root,
        timeout_default=30,
        timeout_max=120,
        stdout_max_bytes=32768,
        stderr_max_bytes=32768,
    )


def _build_cross_repo_grep_runner(tmp_path: Path) -> ExecutionRunner:
    skills_root = tmp_path / "skills"
    _write_cross_repo_grep_skill(skills_root)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "__init__.py").write_text("", encoding="utf-8")
    return ExecutionRunner(
        src_root=tmp_path,
        skills_root=skills_root,
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
        'symbol_usage --term \\"enqueueInvoice r:github.com/acme/ui\\" --context-lines 1'
    )

    assert workflow_id == "symbol_usage"
    assert args["term"] == "enqueueInvoice r:github.com/acme/ui"
    assert args["context_lines"] == 1


def test_parse_workflow_cli_adds_hint_for_split_value_from_over_escaped_quotes(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    with pytest.raises(ValueError, match="over-escaped quotes"):
        runner.parse_workflow_cli_command('symbol_usage --term \\"enqueueInvoice r:github.com/acme/ui --context-lines 1')


def test_build_cli_argv_tokens_normalizes_flags_and_values() -> None:
    argv = ExecutionRunner._build_cli_argv_tokens(
        {
            "expand_variants": False,
            "context_lines": 1,
            "term": "enqueueInvoice r:github.com/acme/ui",
        }
    )

    assert "--expand-variants" in argv
    assert "--context-lines" in argv
    assert "--term" in argv
    assert "false" in argv
    assert "1" in argv
    assert "enqueueInvoice r:github.com/acme/ui" in argv


def test_build_environment_omits_github_secrets_and_injects_rpc_url(tmp_path: Path, monkeypatch) -> None:
    runner = _build_runner(tmp_path)
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "456")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "/tmp/github-app.pem")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_example")

    env = runner._build_environment(
        github_rpc_url="http://127.0.0.1:9999/internal/github-rpc",
    )

    assert env["CRPR_GITHUB_RPC_URL"] == "http://127.0.0.1:9999/internal/github-rpc"
    assert "CRPR_GITHUB_RPC_TOKEN" not in env
    assert "GITHUB_APP_ID" not in env
    assert "GITHUB_APP_INSTALLATION_ID" not in env
    assert "GITHUB_APP_PRIVATE_KEY_PATH" not in env
    assert "GITHUB_APP_PRIVATE_KEY" not in env
    assert "GITHUB_TOKEN" not in env


def test_run_custom_workflow_code_accepts_plain_text_stdout() -> None:
    project_root = Path(__file__).resolve().parents[1]
    runner = ExecutionRunner(
        src_root=project_root / "src",
        skills_root=project_root / "src" / "skills",
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
        skills_root=project_root / "src" / "skills",
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


def test_workflow_requires_pr_scope_matches_expected_workflows() -> None:
    assert ExecutionRunner.workflow_requires_pr_scope("pr_impact_assessment") is True
    assert ExecutionRunner.workflow_requires_pr_scope("file_context_reader") is True
    assert ExecutionRunner.workflow_requires_pr_scope("cross_repo_grep") is True
    assert ExecutionRunner.workflow_requires_pr_scope("symbol_usage") is True
    assert ExecutionRunner.workflow_requires_pr_scope("symbol_definition") is True
    assert ExecutionRunner.workflow_requires_pr_scope("repo_discovery") is True


def test_parse_workflow_cli_rejects_pr_identity_flags_for_scoped_workflow() -> None:
    project_root = Path(__file__).resolve().parents[1]
    runner = ExecutionRunner(
        src_root=project_root / "src",
        skills_root=project_root / "src" / "skills",
        timeout_default=30,
        timeout_max=120,
        stdout_max_bytes=32768,
        stderr_max_bytes=32768,
    )

    with pytest.raises(ValueError, match="unknown flag"):
        runner.parse_workflow_cli_command("pr_impact_assessment --owner acme --repo checkout --pr-number 12")


def test_parse_workflow_cli_rejects_thread_scope_flags_for_non_pr_workflow() -> None:
    project_root = Path(__file__).resolve().parents[1]
    runner = ExecutionRunner(
        src_root=project_root / "src",
        skills_root=project_root / "src" / "skills",
        timeout_default=30,
        timeout_max=120,
        stdout_max_bytes=32768,
        stderr_max_bytes=32768,
    )

    with pytest.raises(ValueError, match="unknown flag"):
        runner.parse_workflow_cli_command(
            "symbol_usage --term ProcessOrder --thread-owner acme --thread-repo checkout --thread-pr-number 22"
        )


def test_run_workflow_script_passes_args_through_to_subprocess(tmp_path: Path, monkeypatch) -> None:
    runner = _build_runner(tmp_path)
    captured: dict[str, object] = {}

    async def _fake_execute(*, command, **kwargs):  # noqa: ANN001
        captured["command"] = list(command)
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(runner, "_execute", _fake_execute)

    result = asyncio.run(
        runner.run_workflow_script(
            workflow_id="symbol_usage",
            args={
                "term": "ProcessOrder",
                "thread_owner": "acme",
                "thread_repo": "checkout",
                "thread_pr_number": 22,
            },
            timeout_seconds=30,
        )
    )

    assert result.success is True
    argv = captured["command"]
    assert isinstance(argv, list)
    bootstrap = " ".join(str(token) for token in argv)
    assert "--thread-owner" in bootstrap
    assert "--thread-repo" in bootstrap
    assert "--thread-pr-number" in bootstrap


def test_parse_workflow_cli_accepts_positional_args_for_workflow(tmp_path: Path) -> None:
    runner = _build_cross_repo_grep_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command('cross_repo_grep "send_event" src/app.py')

    assert workflow_id == "cross_repo_grep"
    assert args["regexp"] == "send_event"
    assert args["path"] == "src/app.py"
    assert args["context_lines"] == 0


def test_parse_workflow_cli_accepts_short_boolean_and_short_value_flags(tmp_path: Path) -> None:
    runner = _build_cross_repo_grep_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command('cross_repo_grep -in -C 5 "send_event" src/app.py')

    assert workflow_id == "cross_repo_grep"
    assert args["ignore_case"] is True
    assert args["line_number"] is True
    assert args["context_lines"] == 5


def test_parse_workflow_cli_accepts_compact_short_value_flag(tmp_path: Path) -> None:
    runner = _build_cross_repo_grep_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command('cross_repo_grep -C5 "send_event" src/app.py')

    assert workflow_id == "cross_repo_grep"
    assert args["context_lines"] == 5


def test_parse_workflow_cli_accepts_long_boolean_without_explicit_value(tmp_path: Path) -> None:
    runner = _build_cross_repo_grep_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command('cross_repo_grep --ignore-case "send_event" src/app.py')

    assert workflow_id == "cross_repo_grep"
    assert args["ignore_case"] is True


def test_parse_workflow_cli_accepts_terminator_for_dash_prefixed_pattern(tmp_path: Path) -> None:
    runner = _build_cross_repo_grep_runner(tmp_path)

    workflow_id, args = runner.parse_workflow_cli_command("cross_repo_grep -- -foo src/app.py")

    assert workflow_id == "cross_repo_grep"
    assert args["regexp"] == "-foo"
    assert args["path"] == "src/app.py"
