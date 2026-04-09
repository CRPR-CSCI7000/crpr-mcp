import asyncio
from pathlib import Path

from src.config import ServerConfig
from src.execution.models import ExecutionResult
from src.internal_context import ContextLifecycleError, ResolvedContext
from src.server import CrprMCPServer


def _build_server(monkeypatch, tmp_path: Path) -> CrprMCPServer:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    monkeypatch.setenv("EXECUTION_TIMEOUT_SECONDS", "60")
    return CrprMCPServer(ServerConfig())


def test_run_workflow_cli_preflight_ensures_context_before_subprocess(monkeypatch, tmp_path: Path) -> None:
    server = _build_server(monkeypatch, tmp_path)
    call_order: list[str] = []

    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("pr_impact_assessment", {}),
    )
    monkeypatch.setattr(
        "src.server.get_http_headers",
        lambda include_all=True: {  # noqa: ARG005
            "x-crpr-thread-owner": "acme",
            "x-crpr-thread-repo": "checkout",
            "x-crpr-thread-pr-number": "12",
        },
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
        assert args == {}
        assert timeout_seconds == 60
        assert extra_env is not None
        assert extra_env["CRPR_CONTEXT_ID"] == "ctx_123"
        assert enforce_timeout is True
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="pr_impact_assessment"))

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
    monkeypatch.setattr("src.server.get_http_headers", lambda include_all=True: {})  # noqa: ARG005

    called = {"run": False}

    async def fake_run(*args, **kwargs):
        called["run"] = True
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="pr_impact_assessment"))

    assert called["run"] is False
    assert "workflow preflight failed" in markdown


def test_run_workflow_cli_returns_preflight_error_when_context_build_fails(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)

    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("pr_impact_assessment", {}),
    )
    monkeypatch.setattr(
        "src.server.get_http_headers",
        lambda include_all=True: {  # noqa: ARG005
            "x-crpr-thread-owner": "acme",
            "x-crpr-thread-repo": "checkout",
            "x-crpr-thread-pr-number": "12",
        },
    )

    async def fake_ensure(owner: str, repo: str, pr_number: int, wait: bool = True) -> ResolvedContext:
        raise ContextLifecycleError("catalog build failed")

    called = {"run": False}

    async def fake_run(*args, **kwargs):
        called["run"] = True
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="pr_impact_assessment"))

    assert called["run"] is False
    assert "workflow preflight failed: catalog build failed" in markdown


def test_run_custom_workflow_code_does_not_use_context_lifecycle(monkeypatch, tmp_path: Path) -> None:
    server = _build_server(monkeypatch, tmp_path)

    async def fake_run_custom(
        code: str,
        timeout_seconds: int,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        assert timeout_seconds == 60
        assert extra_env is None
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    async def fail_ensure(*args, **kwargs):
        raise AssertionError("ensure_pr_context must not be called for custom workflow code")

    monkeypatch.setattr(server.execution_runner, "run_custom_workflow_code", fake_run_custom)
    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fail_ensure)

    markdown = asyncio.run(server.run_custom_workflow_code(code="print('ok')"))

    assert "Process status: `success`" in markdown


def test_run_custom_workflow_code_injects_thread_scope_env_from_headers(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.server.get_http_headers",
        lambda include_all=True: {  # noqa: ARG005
            "x-crpr-thread-owner": "acme",
            "x-crpr-thread-repo": "checkout",
            "x-crpr-thread-pr-number": "12",
        },
    )

    call_order: list[str] = []

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

    async def fake_run_custom(
        code: str,
        timeout_seconds: int,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        call_order.append("run")
        assert timeout_seconds == 60
        assert extra_env is not None
        assert extra_env["CRPR_CONTEXT_ID"] == "ctx_123"
        assert extra_env["CRPR_CONTEXT_OWNER"] == "acme"
        assert extra_env["CRPR_CONTEXT_REPO"] == "checkout"
        assert extra_env["CRPR_CONTEXT_PR_NUMBER"] == "12"
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_custom_workflow_code", fake_run_custom)

    markdown = asyncio.run(server.run_custom_workflow_code(code="print('ok')"))

    assert call_order == ["ensure", "run"]
    assert "Process status: `success`" in markdown


def test_run_workflow_cli_cross_repo_grep_ensures_context_before_subprocess(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.server.get_http_headers",
        lambda include_all=True: {  # noqa: ARG005
            "x-crpr-thread-owner": "acme",
            "x-crpr-thread-repo": "checkout",
            "x-crpr-thread-pr-number": "12",
        },
    )
    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("cross_repo_grep", {"regexp": "source", "repo": "github.com/acme/ui"}),
    )

    call_order: list[str] = []

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
        assert workflow_id == "cross_repo_grep"
        assert args == {"regexp": "source", "repo": "github.com/acme/ui"}
        assert timeout_seconds == 60
        assert extra_env is not None
        assert extra_env["CRPR_CONTEXT_ID"] == "ctx_123"
        assert extra_env["CRPR_CONTEXT_OWNER"] == "acme"
        assert extra_env["CRPR_CONTEXT_REPO"] == "checkout"
        assert extra_env["CRPR_CONTEXT_PR_NUMBER"] == "12"
        assert enforce_timeout is True
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="cross_repo_grep source --repo github.com/acme/ui"))

    assert call_order == ["ensure", "run"]
    assert "Process status: `success`" in markdown


def test_run_workflow_cli_symbol_usage_ensures_context_before_subprocess(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.server.get_http_headers",
        lambda include_all=True: {  # noqa: ARG005
            "x-crpr-thread-owner": "acme",
            "x-crpr-thread-repo": "checkout",
            "x-crpr-thread-pr-number": "12",
        },
    )
    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("symbol_usage", {"term": "ProcessOrder"}),
    )

    call_order: list[str] = []

    async def fake_ensure(owner: str, repo: str, pr_number: int, wait: bool = True) -> ResolvedContext:
        call_order.append("ensure")
        assert owner == "acme"
        assert repo == "checkout"
        assert pr_number == 12
        assert wait is True
        return ResolvedContext(
            context_id="ctx_456",
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
        assert workflow_id == "symbol_usage"
        assert args == {"term": "ProcessOrder"}
        assert timeout_seconds == 60
        assert extra_env is not None
        assert extra_env["CRPR_CONTEXT_ID"] == "ctx_456"
        assert extra_env["CRPR_CONTEXT_OWNER"] == "acme"
        assert extra_env["CRPR_CONTEXT_REPO"] == "checkout"
        assert extra_env["CRPR_CONTEXT_PR_NUMBER"] == "12"
        assert enforce_timeout is True
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown = asyncio.run(server.run_workflow_cli(command="symbol_usage ProcessOrder"))

    assert call_order == ["ensure", "run"]
    assert "Process status: `success`" in markdown


def test_run_workflow_cli_pr_scoped_workflow_reuses_ensure_within_same_turn(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    headers = {
        "x-crpr-thread-owner": "acme",
        "x-crpr-thread-repo": "checkout",
        "x-crpr-thread-pr-number": "12",
        "x-crpr-thread-id": "thread-123",
        "x-crpr-thread-turn": "5",
    }
    monkeypatch.setattr("src.server.get_http_headers", lambda include_all=True: headers)  # noqa: ARG005
    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("cross_repo_grep", {"regexp": "source", "repo": "github.com/acme/ui"}),
    )

    ensure_calls = {"count": 0}
    seen_context_ids: list[str] = []

    async def fake_ensure(owner: str, repo: str, pr_number: int, wait: bool = True) -> ResolvedContext:
        ensure_calls["count"] += 1
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
        assert workflow_id == "cross_repo_grep"
        assert extra_env is not None
        seen_context_ids.append(extra_env["CRPR_CONTEXT_ID"])
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown_1 = asyncio.run(server.run_workflow_cli(command="cross_repo_grep source --repo github.com/acme/ui"))
    markdown_2 = asyncio.run(server.run_workflow_cli(command="cross_repo_grep source --repo github.com/acme/ui"))

    assert ensure_calls["count"] == 1
    assert seen_context_ids == ["ctx_123", "ctx_123"]
    assert "Process status: `success`" in markdown_1
    assert "Process status: `success`" in markdown_2


def test_run_workflow_cli_pr_scoped_workflow_reensures_on_new_turn(
    monkeypatch, tmp_path: Path
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    headers = {
        "x-crpr-thread-owner": "acme",
        "x-crpr-thread-repo": "checkout",
        "x-crpr-thread-pr-number": "12",
        "x-crpr-thread-id": "thread-123",
        "x-crpr-thread-turn": "5",
    }
    monkeypatch.setattr("src.server.get_http_headers", lambda include_all=True: headers)  # noqa: ARG005
    monkeypatch.setattr(
        server.execution_runner,
        "parse_workflow_cli_command",
        lambda command: ("cross_repo_grep", {"regexp": "source", "repo": "github.com/acme/ui"}),
    )

    ensure_calls = {"count": 0}
    seen_context_ids: list[str] = []

    async def fake_ensure(owner: str, repo: str, pr_number: int, wait: bool = True) -> ResolvedContext:
        ensure_calls["count"] += 1
        return ResolvedContext(
            context_id=f"ctx_{ensure_calls['count']}",
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
        assert workflow_id == "cross_repo_grep"
        assert extra_env is not None
        seen_context_ids.append(extra_env["CRPR_CONTEXT_ID"])
        return ExecutionResult(success=True, exit_code=0, result_json={"ok": True})

    monkeypatch.setattr(server.context_lifecycle, "ensure_pr_context", fake_ensure)
    monkeypatch.setattr(server.execution_runner, "run_workflow_script", fake_run)

    markdown_1 = asyncio.run(server.run_workflow_cli(command="cross_repo_grep source --repo github.com/acme/ui"))
    headers["x-crpr-thread-turn"] = "6"
    markdown_2 = asyncio.run(server.run_workflow_cli(command="cross_repo_grep source --repo github.com/acme/ui"))

    assert ensure_calls["count"] == 2
    assert seen_context_ids == ["ctx_1", "ctx_2"]
    assert "Process status: `success`" in markdown_1
    assert "Process status: `success`" in markdown_2
