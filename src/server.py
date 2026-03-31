import asyncio
import json
import logging
import pathlib
import signal
from typing import Any, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import ServerConfig
from .execution.github_auth import GitHubRuntimeError
from .execution.github_rpc_proxy import GitHubRPCProxy
from .execution.models import (
    CustomWorkflowCodeRunRequest,
    ExecutionResult,
    GitHubRPCRequest,
    GitHubRPCResponse,
    WorkflowCliRunRequest,
)
from .execution.runner import ExecutionRunner
from .execution.safety import get_allowed_runtime_modules
from .internal_context import ContextLifecycleError, ContextLifecycleManager
from .skills.registry import SkillRegistry
from .skills.workflows.renderers import format_workflow_result_markdown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

HEADER_THREAD_OWNER = "x-crpr-thread-owner"
HEADER_THREAD_REPO = "x-crpr-thread-repo"
HEADER_THREAD_PR_NUMBER = "x-crpr-thread-pr-number"

class CrprMCPServer:
    _DISCOVERY_ITEMS_PLACEHOLDER = "{{DISCOVERY_ITEMS}}"

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.server = FastMCP()
        self._shutdown_requested = False

        self._setup_runtime()
        self._validate_view_placeholders()
        self._load_tool_descriptions()

    def _setup_runtime(self) -> None:
        self.src_root = pathlib.Path(__file__).parent
        self.skills_root = self.src_root / "skills"

        self.skill_registry = SkillRegistry(skills_root=self.skills_root)
        self.github_rpc_proxy = GitHubRPCProxy()
        github_rpc_url = f"http://127.0.0.1:{self.config.streamable_http_port}/internal/github-rpc"
        self.execution_runner = ExecutionRunner(
            src_root=self.src_root,
            skills_root=self.skills_root,
            timeout_default=self.config.execution_timeout_default,
            timeout_max=self.config.execution_timeout_max,
            stdout_max_bytes=self.config.execution_stdout_max_bytes,
            stderr_max_bytes=self.config.execution_stderr_max_bytes,
            github_rpc_url=github_rpc_url,
        )
        self.context_lifecycle = ContextLifecycleManager(
            zoekt_api_url=self.config.zoekt_api_url,
        )

    def _load_tool_descriptions(self) -> None:
        self.list_capabilities_description = self._tool_description_with_default(
            "list_capabilities",
            "List available workflow and execution-pattern capabilities.",
        )
        self.read_capability_description = self._tool_description_with_default(
            "read_capability",
            "Read the full capability document by id.",
        )
        self.run_workflow_cli_description = self._tool_description_with_default(
            "run_workflow_cli",
            "Run a prebuilt workflow using CLI-style flags.",
        )
        self.run_custom_workflow_code_description = self._tool_description_with_default(
            "run_custom_workflow_code",
            "Run custom workflow code in an isolated subprocess with safety checks.",
        )

    def _tool_description_with_default(self, tool_id: str, default: str) -> str:
        try:
            description = self.skill_registry.tool_description(tool_id)
            if isinstance(description, str) and description.strip():
                return description
        except Exception:
            logger.warning("Tool description missing from skills, using fallback: %s", tool_id)
        return default

    def signal_handler(self, sig: int, frame: Any = None) -> None:
        """Handle termination signals for graceful shutdown."""
        logger.info("Received signal %s, initiating graceful shutdown...", sig)
        self._shutdown_requested = True

    async def list_capabilities(
        self,
        view: Literal["capabilities", "runtime_helpers"] = "capabilities",
    ) -> str:
        if self._shutdown_requested:
            logger.info("Shutdown in progress, declining new capability list requests")
            return "## Capability List\n\nServer is shutting down."

        try:
            if view == "runtime_helpers":
                helper_cards = await asyncio.to_thread(self._runtime_helper_cards)
                header = await asyncio.to_thread(
                    self.skill_registry.render_view_header,
                    "views.runtime_helpers",
                    total=len(helper_cards),
                )
                return self._render_discovery_view_markdown(
                    header_markdown=header,
                    cards=helper_cards,
                    empty_message="No runtime helpers available.",
                )

            capability_cards = await asyncio.to_thread(self._capability_cards)
            header = await asyncio.to_thread(
                self.skill_registry.render_view_header,
                "views.list_capabilities",
                total=len(capability_cards),
            )
            return self._render_discovery_view_markdown(
                header_markdown=header,
                cards=capability_cards,
                empty_message="No capabilities available.",
            )
        except Exception as exc:
            logger.error("list_capabilities failed: %s", exc)
            return f"## Capability List\n\nError: `{exc}`"

    async def read_capability(self, capability_id: str) -> str:
        if self._shutdown_requested:
            return self._format_capability_error_markdown(capability_id, "server is shutting down")

        try:
            capability_skill = self.skill_registry.capabilities.get(capability_id)
            if capability_skill is None:
                return self._format_capability_error_markdown(capability_id, f"unknown capability_id: {capability_id}")
            capability_doc = capability_skill.read_doc

            if capability_id != "execution.run_custom_workflow_code":
                return capability_doc

            runtime_helper_details = await asyncio.to_thread(self._runtime_helper_details)
            return self._append_runtime_helper_details(
                capability_doc=capability_doc,
                runtime_helper_details=runtime_helper_details,
                allowed_runtime_modules=get_allowed_runtime_modules(),
            )
        except Exception as exc:
            logger.error("read_capability failed: %s", exc)
            return self._format_capability_error_markdown(capability_id, f"runner internal exception: {exc}")

    async def run_workflow_cli(
        self,
        command: str,
    ) -> str:
        if self._shutdown_requested:
            return self._format_execution_result_markdown(
                "Workflow CLI Execution",
                self._error_execution_result("server is shutting down"),
            )

        try:
            request = WorkflowCliRunRequest(
                command=command,
            )
        except Exception as exc:
            return self._format_execution_result_markdown(
                "Workflow CLI Execution",
                self._error_execution_result(f"args validation failure: {exc}", exit_code=2),
            )

        try:
            workflow_id, args = self.execution_runner.parse_workflow_cli_command(request.command)
            extra_env: dict[str, str] = {}

            if self.execution_runner.workflow_requires_pr_scope(workflow_id):
                pr_identity = self._resolve_thread_pr_identity_from_headers()
                if pr_identity is None:
                    return self._format_execution_result_markdown(
                        "Workflow CLI Execution",
                        self._error_execution_result(
                            "workflow preflight failed: PR-scoped workflow requires owner/repo/pr_number "
                            "from thread-scoped MCP headers"
                        ),
                    )

                owner, repo, pr_number = pr_identity
                resolved_context = await self.context_lifecycle.ensure_pr_context(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    wait=True,
                )
                extra_env.update(
                    {
                        "CRPR_CONTEXT_ID": resolved_context.context_id,
                        "CRPR_CONTEXT_OWNER": resolved_context.owner,
                        "CRPR_CONTEXT_REPO": resolved_context.repo,
                        "CRPR_CONTEXT_PR_NUMBER": str(resolved_context.pr_number),
                        "CRPR_CONTEXT_ANCHOR_CREATED_AT": resolved_context.anchor_created_at,
                        "CRPR_CONTEXT_MANIFEST_PATH": resolved_context.manifest_path,
                    }
                )

            result = await self.execution_runner.run_workflow_script(
                workflow_id=workflow_id,
                args=args,
                timeout_seconds=self.config.execution_timeout_default,
                extra_env=extra_env,
                enforce_timeout=True,
            )
            return format_workflow_result_markdown(workflow_id, result)
        except ContextLifecycleError as exc:
            return self._format_execution_result_markdown(
                "Workflow CLI Execution",
                self._error_execution_result(f"workflow preflight failed: {exc}"),
            )
        except ValueError as exc:
            return self._format_execution_result_markdown(
                "Workflow CLI Execution",
                self._error_execution_result(str(exc), exit_code=2),
            )
        except Exception as exc:
            logger.exception("run_workflow_cli internal exception")
            return self._format_execution_result_markdown(
                "Workflow CLI Execution",
                self._error_execution_result(f"runner internal exception: {exc}"),
            )

    async def run_custom_workflow_code(
        self,
        code: str,
    ) -> str:
        if self._shutdown_requested:
            return self._format_execution_result_markdown(
                "Custom Workflow Code Execution",
                self._error_execution_result("server is shutting down"),
            )

        try:
            request = CustomWorkflowCodeRunRequest(
                code=code,
            )
        except Exception as exc:
            return self._format_execution_result_markdown(
                "Custom Workflow Code Execution",
                self._error_execution_result(f"args validation failure: {exc}", exit_code=2),
            )

        try:
            extra_env: dict[str, str] = {}
            pr_identity = self._resolve_thread_pr_identity_from_headers()
            if pr_identity is not None:
                owner, repo, pr_number = pr_identity
                extra_env.update(
                    {
                        "CRPR_CONTEXT_OWNER": owner,
                        "CRPR_CONTEXT_REPO": repo,
                        "CRPR_CONTEXT_PR_NUMBER": str(pr_number),
                    }
                )
            result = await self.execution_runner.run_custom_workflow_code(
                code=request.code,
                timeout_seconds=self.config.execution_timeout_default,
                extra_env=extra_env or None,
            )
            return self._format_execution_result_markdown("Custom Workflow Code Execution", result)
        except Exception as exc:
            logger.exception("run_custom_workflow_code internal exception")
            return self._format_execution_result_markdown(
                "Custom Workflow Code Execution",
                self._error_execution_result(f"runner internal exception: {exc}"),
            )

    @staticmethod
    def _resolve_thread_pr_identity_from_headers() -> tuple[str, str, int] | None:
        headers = get_http_headers(include_all=True)
        owner = str(headers.get(HEADER_THREAD_OWNER, "")).strip()
        repo = str(headers.get(HEADER_THREAD_REPO, "")).strip()
        try:
            pr_number = int(headers.get(HEADER_THREAD_PR_NUMBER))
        except (TypeError, ValueError):
            pr_number = 0
        if not owner or not repo or pr_number <= 0:
            return None
        return owner, repo, pr_number

    @staticmethod
    def _format_capability_error_markdown(capability_id: str, message: str) -> str:
        return "\n".join(
            [
                f"## Capability: `{capability_id}`",
                "",
                "- Kind: `error`",
                "",
                "### Description",
                message,
            ]
        )

    @staticmethod
    def _error_execution_result(
        message: str,
        exit_code: int = 70,
        safety_rejections: list[str] | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            exit_code=exit_code,
            stdout="",
            stderr=message,
            result_json=None,
            timing_ms=0,
            safety_rejections=safety_rejections or [],
        )

    @staticmethod
    def _markdown_block_lines(markdown: str) -> list[str]:
        normalized = str(markdown).strip()
        if not normalized:
            return []
        return [line.rstrip() for line in normalized.splitlines()]

    def _capability_cards(self) -> list[tuple[str, str]]:
        skills = sorted(self.skill_registry.capabilities.values(), key=lambda skill: (skill.order, skill.id))
        return [(skill.id, skill.list_card) for skill in skills]

    def _runtime_helper_cards(self) -> list[tuple[str, str]]:
        helpers = sorted(self.skill_registry.runtime_helpers.values(), key=lambda helper: (helper.order, helper.id))
        return [(helper.id, helper.list_card) for helper in helpers]

    def _runtime_helper_details(self) -> list[tuple[str, str]]:
        helpers = sorted(self.skill_registry.runtime_helpers.values(), key=lambda helper: (helper.order, helper.id))
        return [(helper.id, helper.detail_doc) for helper in helpers]

    def _validate_view_placeholders(self) -> None:
        required_view_ids = ("views.list_capabilities", "views.runtime_helpers")
        for view_id in required_view_ids:
            header = self.skill_registry.render_view_header(view_id, total=0)
            placeholder_count = header.count(self._DISCOVERY_ITEMS_PLACEHOLDER)
            if placeholder_count != 1:
                raise ValueError(
                    f"view `{view_id}` must include `{self._DISCOVERY_ITEMS_PLACEHOLDER}` exactly once; "
                    f"found {placeholder_count}"
                )

    @staticmethod
    def _numbered_cards_block_markdown(
        cards: list[tuple[str, str]],
        empty_message: str,
    ) -> str:
        if not cards:
            return empty_message

        lines: list[str] = []
        for index, (doc_id, card_markdown) in enumerate(cards, start=1):
            lines.append(f"### {index}. `{doc_id}`")
            lines.extend(CrprMCPServer._markdown_block_lines(card_markdown))
            if index < len(cards):
                lines.append("")

        return "\n".join(lines).rstrip()

    def _render_discovery_view_markdown(
        self,
        header_markdown: str,
        cards: list[tuple[str, str]],
        empty_message: str,
    ) -> str:
        placeholder_count = header_markdown.count(self._DISCOVERY_ITEMS_PLACEHOLDER)
        if placeholder_count != 1:
            raise ValueError(
                f"view header must include `{self._DISCOVERY_ITEMS_PLACEHOLDER}` exactly once; found {placeholder_count}"
            )

        cards_block = self._numbered_cards_block_markdown(cards=cards, empty_message=empty_message)
        rendered = header_markdown.replace(self._DISCOVERY_ITEMS_PLACEHOLDER, cards_block)
        return "\n".join(self._markdown_block_lines(rendered)).rstrip()

    @staticmethod
    def _append_runtime_helper_details(
        capability_doc: str,
        runtime_helper_details: list[tuple[str, str]],
        allowed_runtime_modules: list[str],
    ) -> str:
        lines = CrprMCPServer._markdown_block_lines(capability_doc)
        lines.extend(["", "### Runtime Helpers", "Allowed runtime modules:"])

        if allowed_runtime_modules:
            lines.extend([f"- `{module}`" for module in allowed_runtime_modules])
        else:
            lines.append("- (none)")

        if not runtime_helper_details:
            lines.extend(["", "No runtime helpers registered."])
            return "\n".join(lines).rstrip()

        for _, detail_markdown in runtime_helper_details:
            lines.extend(["", *CrprMCPServer._markdown_block_lines(detail_markdown)])

        return "\n".join(lines).rstrip()

    @staticmethod
    def _format_execution_result_markdown(title: str, result: ExecutionResult) -> str:
        process_status = "success" if result.success else "failure"
        output_status = CrprMCPServer._infer_output_status(result)
        lines = [
            f"## {title}",
            "",
            f"- Process status: `{process_status}`",
            f"- Output status: `{output_status}`",
            f"- Exit code: `{result.exit_code}`",
            f"- Timing (ms): `{result.timing_ms}`",
        ]
        if result.safety_rejections:
            lines.append(f"- Safety rejections: `{len(result.safety_rejections)}`")
            lines.extend([f"  - {rejection}" for rejection in result.safety_rejections])

        lines.extend(["", "### Result JSON", "```json", json.dumps(result.result_json, indent=2, ensure_ascii=True), "```"])

        if result.stdout:
            lines.extend(["", "### Stdout", "```text", result.stdout, "```"])
        if result.stderr:
            lines.extend(["", "### Stderr", "```text", result.stderr, "```"])

        return "\n".join(lines)

    @staticmethod
    def _infer_output_status(result: ExecutionResult) -> str:
        if result.result_json is not None:
            return "parsed"

        stderr_lc = (result.stderr or "").lower()
        if "malformed result marker json" in stderr_lc:
            return "parse_error"
        if "result marker not found" in stderr_lc:
            return "missing_result_marker"
        if result.success:
            return "missing_payload"
        return "not_available"

    def _register_tools(self) -> None:
        tools = [
            (self.list_capabilities, "list_capabilities", self.list_capabilities_description),
            (self.read_capability, "read_capability", self.read_capability_description),
            (self.run_workflow_cli, "run_workflow_cli", self.run_workflow_cli_description),
            (
                self.run_custom_workflow_code,
                "run_custom_workflow_code",
                self.run_custom_workflow_code_description,
            ),
        ]

        for tool_func, tool_name, description in tools:
            self.server.tool(tool_func, name=tool_name, description=description)
            logger.info("Registered tool: %s", tool_name)

    def _register_http_routes(self) -> None:
        @self.server.custom_route("/internal/github-rpc", methods=["POST"])
        async def github_rpc(request: Request) -> Response:
            try:
                raw_payload = await request.json()
            except Exception:
                return JSONResponse({"ok": False, "error": "invalid json payload"}, status_code=400)

            try:
                rpc_request = GitHubRPCRequest.model_validate(raw_payload)
            except Exception as exc:
                return JSONResponse({"ok": False, "error": f"invalid rpc request: {exc}"}, status_code=400)

            try:
                result = await asyncio.to_thread(
                    self.github_rpc_proxy.dispatch,
                    rpc_request.method,
                    rpc_request.params,
                )
            except GitHubRuntimeError as exc:
                response = GitHubRPCResponse(ok=False, error=str(exc))
                return JSONResponse(response.model_dump(mode="json"), status_code=400)
            except Exception as exc:
                logger.exception("GitHub RPC dispatch failed: %s", exc)
                response = GitHubRPCResponse(ok=False, error="internal proxy error")
                return JSONResponse(response.model_dump(mode="json"), status_code=500)

            response = GitHubRPCResponse(ok=True, result=result)
            return JSONResponse(response.model_dump(mode="json"))

        @self.server.custom_route("/health", methods=["GET"])
        async def health_check(request: Request) -> Response:
            return JSONResponse({"status": "ok", "service": "crpr-mcp"})

        @self.server.custom_route("/ready", methods=["GET"])
        async def readiness_check(request: Request) -> Response:
            try:
                if not hasattr(self, "skill_registry") or self.skill_registry is None:
                    return JSONResponse({"status": "not_ready", "reason": "skill_registry_unavailable"}, status_code=503)

                if not hasattr(self, "execution_runner") or self.execution_runner is None:
                    return JSONResponse({"status": "not_ready", "reason": "execution_runner_unavailable"}, status_code=503)
                if not hasattr(self, "context_lifecycle") or self.context_lifecycle is None:
                    return JSONResponse({"status": "not_ready", "reason": "context_lifecycle_unavailable"}, status_code=503)

                if not self.skills_root.exists():
                    return JSONResponse(
                        {"status": "not_ready", "reason": f"skills_root_missing:{self.skills_root}"},
                        status_code=503,
                    )

                return JSONResponse(
                    {
                        "status": "ready",
                        "service": "crpr-mcp",
                        "mode": "capability-workflow-executor",
                    }
                )
            except Exception as exc:
                logger.error("Readiness check failed: %s", exc)
                return JSONResponse({"status": "error", "reason": str(exc)}, status_code=503)

    async def _run_server(self) -> None:
        tasks = [
            self.server.run_http_async(
                transport="streamable-http",
                host="0.0.0.0",
                path="/crpr/mcp",
                port=self.config.streamable_http_port,
            ),
            self.server.run_http_async(
                transport="sse",
                host="0.0.0.0",
                path="/crpr/sse",
                port=self.config.sse_port,
            ),
        ]
        await asyncio.gather(*tasks)

    async def run(self) -> None:
        signal.signal(signal.SIGINT, lambda sig, frame: self.signal_handler(sig, frame))
        signal.signal(signal.SIGTERM, lambda sig, frame: self.signal_handler(sig, frame))

        self._register_tools()
        self._register_http_routes()

        try:
            logger.info("Starting CRPR MCP server...")
            await self._run_server()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt (CTRL+C)")
        except Exception as exc:
            logger.error("Server error: %s", exc)
            raise
        finally:
            logger.info("Server has shut down.")


def main() -> None:
    config = ServerConfig()
    server = CrprMCPServer(config)
    asyncio.run(server.run())

if __name__ == "__main__":
    main()
