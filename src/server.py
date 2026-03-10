import asyncio
import json
import logging
import pathlib
import signal
from typing import Any, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .capabilities import CapabilityCatalog, CapabilityDoc, CapabilityHit, RuntimeHelperDoc
from .config import ServerConfig
from .execution import CustomWorkflowCodeRunRequest, ExecutionResult, ExecutionRunner, WorkflowCliRunRequest
from .execution.safety import get_allowed_runtime_modules
from .prompts import PromptManager
from .workflows import format_workflow_result_markdown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

class ZoektMCPServer:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.server = FastMCP()
        self._shutdown_requested = False

        self._setup_runtime()
        self._load_prompts()

    def _setup_runtime(self) -> None:
        self.src_root = pathlib.Path(__file__).parent
        self.manifest_path = self.src_root / "workflows" / "manifest.yaml"

        self.capability_catalog = CapabilityCatalog(self.manifest_path)
        self.execution_runner = ExecutionRunner(
            src_root=self.src_root,
            manifest_path=self.manifest_path,
            timeout_default=self.config.execution_timeout_default,
            timeout_max=self.config.execution_timeout_max,
            stdout_max_bytes=self.config.execution_stdout_max_bytes,
            stderr_max_bytes=self.config.execution_stderr_max_bytes,
        )

    def _load_prompts(self) -> None:
        prompt_path = pathlib.Path(__file__).parent / "prompts" / "prompts.yaml"
        prompt_manager = PromptManager(file_path=prompt_path)

        self.list_capabilities_description = self._load_prompt_with_default(
            prompt_manager,
            "tools.list_capabilities",
            "List available workflow and execution-pattern capabilities.",
        )
        self.read_capability_description = self._load_prompt_with_default(
            prompt_manager,
            "tools.read_capability",
            "Read the full capability document by id.",
        )
        self.run_workflow_cli_description = self._load_prompt_with_default(
            prompt_manager,
            "tools.run_workflow_cli",
            "Run a prebuilt workflow using CLI-style flags.",
        )
        self.run_custom_workflow_code_description = self._load_prompt_with_default(
            prompt_manager,
            "tools.run_custom_workflow_code",
            "Run custom workflow code in an isolated subprocess with safety checks.",
        )

    @staticmethod
    def _load_prompt_with_default(prompt_manager: PromptManager, key: str, default: str) -> str:
        try:
            prompt = prompt_manager._load_prompt(key)
            if isinstance(prompt, str) and prompt.strip():
                return prompt
        except Exception:
            logger.warning("Prompt key missing, using fallback: %s", key)
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
                helpers = await asyncio.to_thread(self.capability_catalog.runtime_helpers)
                return self._format_runtime_helper_list_markdown(helpers=helpers)

            hits = await asyncio.to_thread(self.capability_catalog.list_capabilities)
            return self._format_capability_list_markdown(hits=hits)
        except Exception as exc:
            logger.error("list_capabilities failed: %s", exc)
            return f"## Capability List\n\nError: `{exc}`"

    async def read_capability(self, capability_id: str) -> str:
        if self._shutdown_requested:
            return self._format_capability_doc_markdown(
                self._error_capability_doc(capability_id, "server is shutting down")
            )

        try:
            capability = await asyncio.to_thread(self.capability_catalog.read, capability_id)
            if capability is None:
                capability = self._error_capability_doc(capability_id, f"unknown capability_id: {capability_id}")

            runtime_helpers: list[RuntimeHelperDoc] | None = None
            allowed_runtime_modules: list[str] | None = None
            if capability.id == "execution.run_custom_workflow_code" and capability.kind != "error":
                runtime_helpers = await asyncio.to_thread(self.capability_catalog.runtime_helpers)
                allowed_runtime_modules = get_allowed_runtime_modules()

            return self._format_capability_doc_markdown(
                capability,
                runtime_helpers=runtime_helpers,
                allowed_runtime_modules=allowed_runtime_modules,
            )
        except Exception as exc:
            logger.error("read_capability failed: %s", exc)
            return self._format_capability_doc_markdown(
                self._error_capability_doc(capability_id, f"runner internal exception: {exc}")
            )

    async def run_workflow_cli(
        self,
        command: str,
        timeout_seconds: int = 30,
    ) -> str:
        if self._shutdown_requested:
            return self._format_execution_result_markdown(
                "Workflow CLI Execution",
                self._error_execution_result("server is shutting down"),
            )

        try:
            request = WorkflowCliRunRequest(
                command=command,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            return self._format_execution_result_markdown(
                "Workflow CLI Execution",
                self._error_execution_result(f"args validation failure: {exc}", exit_code=2),
            )

        try:
            workflow_id, result = await self.execution_runner.run_workflow_cli_command(
                command=request.command,
                timeout_seconds=request.timeout_seconds,
            )
            return format_workflow_result_markdown(workflow_id, result)
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
        timeout_seconds: int = 30,
    ) -> str:
        if self._shutdown_requested:
            return self._format_execution_result_markdown(
                "Custom Workflow Code Execution",
                self._error_execution_result("server is shutting down"),
            )

        try:
            request = CustomWorkflowCodeRunRequest(
                code=code,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            return self._format_execution_result_markdown(
                "Custom Workflow Code Execution",
                self._error_execution_result(f"args validation failure: {exc}", exit_code=2),
            )

        try:
            result = await self.execution_runner.run_custom_workflow_code(
                code=request.code,
                timeout_seconds=request.timeout_seconds,
            )
            return self._format_execution_result_markdown("Custom Workflow Code Execution", result)
        except Exception as exc:
            logger.exception("run_custom_workflow_code internal exception")
            return self._format_execution_result_markdown(
                "Custom Workflow Code Execution",
                self._error_execution_result(f"runner internal exception: {exc}"),
            )

    @staticmethod
    def _error_capability_doc(capability_id: str, message: str) -> CapabilityDoc:
        return CapabilityDoc(
            id=capability_id,
            kind="error",
            description=message,
            arg_schema={},
            examples=[],
            constraints=[],
            expected_output_shape={"error": "string"},
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
    def _format_capability_list_markdown(hits: list[CapabilityHit]) -> str:
        lines = ["## Capability List", "", f"- Total: `{len(hits)}`", ""]
        lines.extend(ZoektMCPServer._capability_kind_legend())
        lines.extend(
            [
                "",
                "### Discovery Policy",
                "- Always call `read_capability` before using any capability from this list.",
                "- `list_capabilities` is intentionally brief and omits arg schemas/examples/constraints.",
                "- Do not execute capabilities from list output alone; use `read_capability` first.",
                "",
            ]
        )
        if not hits:
            lines.append("No capabilities available.")
            return "\n".join(lines)

        for index, hit in enumerate(hits, start=1):
            lines.extend(
                [
                    f"### {index}. `{hit.id}`",
                    f"- Kind: `{hit.kind}`",
                    f"- Summary: {hit.summary}",
                    f"- When to use: {hit.when_to_use}",
                    f"- Next step: `read_capability(capability_id=\"{hit.id}\")`",
                    "- Interface details intentionally omitted here; use `read_capability`.",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    @staticmethod
    def _format_runtime_helper_list_markdown(
        helpers: list[RuntimeHelperDoc],
        *,
        include_header: bool = True,
        include_policy: bool = True,
        detailed: bool = False,
        empty_message: str = "No runtime helpers available.",
    ) -> str:
        lines: list[str] = []
        if include_header:
            lines.extend(["## Runtime Helper List", "", f"- Total: `{len(helpers)}`", ""])

        if include_policy:
            lines.extend(
                [
                    "### Discovery Policy",
                    "- This list is intentionally brief.",
                    "- For full helper schemas/examples, call `read_capability(capability_id=\"execution.run_custom_workflow_code\")`.",
                    "- Before custom-code execution, always read that capability document.",
                    "",
                ]
            )

        if not helpers:
            lines.append(empty_message)
            return "\n".join(lines).rstrip()

        for index, helper in enumerate(helpers, start=1):
            if not detailed:
                lines.extend(
                    [
                        f"### {index}. `{helper.id}`",
                        f"- Summary: {helper.summary or '(none)'}",
                        "- Details: use `read_capability(capability_id=\"execution.run_custom_workflow_code\")`",
                        "",
                    ]
                )
                continue

            signature = ZoektMCPServer._runtime_helper_signature(helper)
            parameters = ZoektMCPServer._runtime_helper_parameter_lines(helper)
            examples = ZoektMCPServer._runtime_helper_example_calls(helper)
            lines.extend(
                [
                    f"#### `{helper.id}`",
                    f"- Summary: {helper.summary or '(none)'}",
                    "- Signature:",
                    "```python",
                    signature,
                    "```",
                    "- Parameters:",
                ]
            )
            if parameters:
                lines.extend(parameters)
            else:
                lines.append("- (none)")

            if examples:
                lines.extend(["- Examples:", "```python", *examples, "```", ""])
            else:
                lines.extend(["- Examples: (none)", ""])

        return "\n".join(lines).rstrip()

    @staticmethod
    def _format_capability_doc_markdown(
        capability: CapabilityDoc,
        runtime_helpers: list[RuntimeHelperDoc] | None = None,
        allowed_runtime_modules: list[str] | None = None,
    ) -> str:
        lines = [f"## Capability: `{capability.id}`", "", f"- Kind: `{capability.kind}`", ""]
        lines.extend(ZoektMCPServer._capability_kind_legend())
        lines.append("")
        if capability.description:
            lines.extend(["### Description", capability.description, ""])

        lines.extend(
            [
                "### Arg Schema",
                "```json",
                json.dumps(capability.arg_schema, indent=2, sort_keys=True, ensure_ascii=True),
                "```",
                "",
                "### Examples",
                "```json",
                json.dumps(capability.examples, indent=2, ensure_ascii=True),
                "```",
                "",
                "### Constraints",
            ]
        )
        if capability.constraints:
            lines.extend([f"- {constraint}" for constraint in capability.constraints])
        else:
            lines.append("- (none)")

        lines.extend(
            [
                "",
                "### Expected Output Shape",
                "```json",
                json.dumps(capability.expected_output_shape, indent=2, sort_keys=True, ensure_ascii=True),
                "```",
            ]
        )

        if runtime_helpers is not None:
            lines.extend(["", "### Runtime Helpers"])
            modules = allowed_runtime_modules or []
            lines.append("Allowed runtime modules:")
            if modules:
                lines.extend([f"- `{module}`" for module in modules])
            else:
                lines.append("- (none)")
            runtime_helper_markdown = ZoektMCPServer._format_runtime_helper_list_markdown(
                runtime_helpers,
                include_header=False,
                include_policy=False,
                detailed=True,
                empty_message="No runtime helpers registered.",
            )
            lines.extend(["", *runtime_helper_markdown.splitlines()])
        return "\n".join(lines)

    @staticmethod
    def _runtime_helper_signature(helper: RuntimeHelperDoc) -> str:
        call_name = helper.id
        if helper.examples:
            first_example = helper.examples[0]
            if isinstance(first_example, dict):
                example_call = first_example.get("call")
                if isinstance(example_call, str) and example_call.strip():
                    call_name = example_call.strip()

        params: list[str] = []
        for arg_name, arg_schema in helper.arg_schema.items():
            schema = arg_schema if isinstance(arg_schema, dict) else {}
            arg_type = ZoektMCPServer._schema_type_to_python(schema.get("type"))
            if schema.get("required"):
                params.append(f"{arg_name}: {arg_type}")
                continue
            if "default" in schema:
                params.append(f"{arg_name}: {arg_type} = {ZoektMCPServer._python_literal(schema.get('default'))}")
                continue
            params.append(f"{arg_name}: {arg_type} | None = None")

        return f"{call_name}({', '.join(params)}) -> Any"

    @staticmethod
    def _runtime_helper_parameter_lines(helper: RuntimeHelperDoc) -> list[str]:
        lines: list[str] = []
        for arg_name, arg_schema in helper.arg_schema.items():
            schema = arg_schema if isinstance(arg_schema, dict) else {}
            arg_type = ZoektMCPServer._schema_type_to_python(schema.get("type"))
            required_text = "required" if schema.get("required") else "optional"
            description = str(schema.get("description", "")).strip()
            default = schema.get("default")

            detail_parts = [f"`{arg_name}` (`{arg_type}`, {required_text})"]
            if "default" in schema:
                detail_parts.append(f"default `{ZoektMCPServer._python_literal(default)}`")
            if description:
                detail_parts.append(description)
            lines.append(f"- {'; '.join(detail_parts)}")
        return lines

    @staticmethod
    def _runtime_helper_example_calls(helper: RuntimeHelperDoc) -> list[str]:
        calls: list[str] = []
        for example in helper.examples:
            if not isinstance(example, dict):
                continue
            call_name = example.get("call")
            if not isinstance(call_name, str) or not call_name.strip():
                continue
            args = example.get("args")
            if not isinstance(args, dict) or not args:
                calls.append(f"{call_name.strip()}()")
                continue

            call_args = ", ".join(f"{key}={ZoektMCPServer._python_literal(value)}" for key, value in args.items())
            calls.append(f"{call_name.strip()}({call_args})")
        return calls

    @staticmethod
    def _schema_type_to_python(schema_type: Any) -> str:
        mapping = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "object": "dict[str, Any]",
            "array": "list[Any]",
        }
        key = str(schema_type or "").strip().lower()
        return mapping.get(key, "Any")

    @staticmethod
    def _python_literal(value: Any) -> str:
        if isinstance(value, str):
            return repr(value)
        return repr(value)

    @staticmethod
    def _capability_kind_legend() -> list[str]:
        return [
            "### Capability Types",
            "- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.",
            "- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).",
        ]

    @staticmethod
    def _format_execution_result_markdown(title: str, result: ExecutionResult) -> str:
        process_status = "success" if result.success else "failure"
        output_status = ZoektMCPServer._infer_output_status(result)
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

    def _register_health_endpoints(self) -> None:
        @self.server.custom_route("/health", methods=["GET"])
        async def health_check(request: Request) -> Response:
            return JSONResponse({"status": "ok", "service": "zoekt-mcp"})

        @self.server.custom_route("/ready", methods=["GET"])
        async def readiness_check(request: Request) -> Response:
            try:
                if not hasattr(self, "capability_catalog") or self.capability_catalog is None:
                    return JSONResponse({"status": "not_ready", "reason": "capability_catalog_unavailable"}, status_code=503)

                if not hasattr(self, "execution_runner") or self.execution_runner is None:
                    return JSONResponse({"status": "not_ready", "reason": "execution_runner_unavailable"}, status_code=503)

                if not self.manifest_path.exists():
                    return JSONResponse(
                        {"status": "not_ready", "reason": f"manifest_missing:{self.manifest_path}"},
                        status_code=503,
                    )

                return JSONResponse(
                    {
                        "status": "ready",
                        "service": "zoekt-mcp",
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
                path="/zoekt/mcp",
                port=self.config.streamable_http_port,
            ),
            self.server.run_http_async(
                transport="sse",
                host="0.0.0.0",
                path="/zoekt/sse",
                port=self.config.sse_port,
            ),
        ]
        await asyncio.gather(*tasks)

    async def run(self) -> None:
        signal.signal(signal.SIGINT, lambda sig, frame: self.signal_handler(sig, frame))
        signal.signal(signal.SIGTERM, lambda sig, frame: self.signal_handler(sig, frame))

        self._register_tools()
        self._register_health_endpoints()

        try:
            logger.info("Starting Zoekt MCP server...")
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
    server = ZoektMCPServer(config)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
