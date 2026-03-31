import asyncio
from pathlib import Path

from src.config import ServerConfig
from src.execution.models import ExecutionResult
from src.internal_context import ContextLifecycleError, ResolvedContext
from src.server import CrprMCPServer


def _build_server(monkeypatch, tmp_path: Path) -> CrprMCPServer:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    return CrprMCPServer(ServerConfig())


def test_run_workflow_cli_preflight_ensures_context_before_subprocess(monkeypatch, tmp_path: Path) -> None:
    server = _build_server(monkeypatch, tmp_path)
    call_order: list[str] = []

    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("pr_impact_assessment", {"owner": "acme", "repo": "checkout", "pr_number": 12}),
    )

    async def fake_ensure(owner: str, repo: str, pr_number: int, wait: bool = True) -> ResolvedContext:
        call_order.append("ensure")
        assert owner == "acme"
        assert repo == "checkout"
        assert pr_number == 12
        assert wait is True
        return ResolvedContext(
            context_id="ctx_123",
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            anchor_created_at="2026-03-30T00:00:00+00:00",
            manifest_path="/tmp/manifest.json",
        )

    async def fake_run(
        workflow_id: str,
        args: dict,
        timeout_seconds: int,
        *,
        extra_env: dict[str, str] | None = None,
        enforce_timeout: bool = True,
    ) -> ExecutionResult:
        call_order.append("run")
        assert workflow_id == "pr_impact_assessment"
        assert args["owner"] == "acme"
        assert extra_env is not None
        assert extra_env["CRPR_CONTEXT_ID"] == "ctx_123"
        assert enforce_timeout is False
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="pr_impact_assessment", timeout_seconds=30))

    assert call_order == ["ensure", "run"]
    assert "Process status: `success`" in markdown


def test_run_workflow_cli_fails_fast_when_pr_identity_missing_from_normalized_payload(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)

    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("pr_impact_assessment", {"limit": 10}),
    )

    called = {"run": False}

    async def fake_run(*args, **kwargs):
        called["run"] = True
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="pr_impact_assessment", timeout_seconds=30))

    assert called["run"] is False
    assert "workflow preflight failed" in markdown


def test_run_workflow_cli_returns_preflight_error_when_context_build_fails(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)

    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("pr_impact_assessment", {"owner": "acme", "repo": "checkout", "pr_number": 12}),
    )

    async def fake_ensure(owner: str, repo: str, pr_number: int, wait: bool = True) -> ResolvedContext:
        raise ContextLifecycleError("catalog build failed")

    called = {"run": False}

    async def fake_run(*args, **kwargs):
        called["run"] = True
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="pr_impact_assessment", timeout_seconds=30))

    assert called["run"] is False
    assert "workflow preflight failed: catalog build failed" in markdown


def test_run_custom_workflow_code_does_not_use_context_lifecycle(monkeypatch, tmp_path: Path) -> None:
    server = _build_server(monkeypatch, tmp_path)

    async def fake_run_custom(code: str, timeout_seconds: int) -> ExecutionResult:
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    async def fail_ensure(*args, **kwargs):
        raise AssertionError("ensure_pr_context must not be called for custom workflow code")

    monkeypatch.setattr(server.execution_runner, "run_custom_workflow_code", fake_run_custom)
    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fail_ensure)

    markdown = asyncio.run(server.run_custom_workflow_code(code="print('ok')", timeout_seconds=30))

    assert "Process status: `success`" in markdown
