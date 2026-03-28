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
from .execution import (
    CustomWorkflowCodeRunRequest,
    ExecutionResult,
    ExecutionRunner,
    GitHubRPCRequest,
    GitHubRPCResponse,
    WorkflowCliRunRequest,
)
from .execution.github_auth import GitHubRuntimeError
from .execution.github_rpc_proxy import GitHubRPCProxy
from .execution.safety import get_allowed_runtime_modules
from .prompts import PromptManager
from .workflows import format_workflow_result_markdown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

class CrprMCPServer:
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
        self.github_rpc_proxy = GitHubRPCProxy()
        github_rpc_url = f"http://127.0.0.1:{self.config.streamable_http_port}/internal/github-rpc"
        self.execution_runner = ExecutionRunner(
            src_root=self.src_root,
            manifest_path=self.manifest_path,
            timeout_default=self.config.execution_timeout_default,
            timeout_max=self.config.execution_timeout_max,
            stdout_max_bytes=self.config.execution_stdout_max_bytes,
            stderr_max_bytes=self.config.execution_stderr_max_bytes,
            github_rpc_url=github_rpc_url,
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
        self.list_capabilities_discovery_policy = self._load_prompt_with_default(
            prompt_manager,
            "guides.list_capabilities_discovery_policy",
            "",
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
            return self._format_capability_list_markdown(
                hits=hits,
                discovery_policy_markdown=self.list_capabilities_discovery_policy,
            )
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
    def _format_capability_list_markdown(
        hits: list[CapabilityHit],
        discovery_policy_markdown: str = "",
    ) -> str:
        lines = ["## Capability List", "", f"- Total: `{len(hits)}`", ""]
        lines.extend(CrprMCPServer._capability_kind_legend())
        policy_lines = CrprMCPServer._markdown_block_lines(discovery_policy_markdown)
        if policy_lines:
            lines.extend(["", *policy_lines, ""])
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
                ]
            )
            if hit.id == "file_context_reader":
                lines.append(
                    "- Scope warning: never use this for source PR repository files; use `pr_file_context_reader`."
                )
            elif hit.id == "pr_file_context_reader":
                lines.append("- Scope note: use this for source PR file reads at `head`/`base` refs.")
            lines.extend(
                [
                    f"- Next step: `read_capability(capability_id=\"{hit.id}\")`",
                    "- Interface details intentionally omitted here; use `read_capability`.",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    @staticmethod
    def _markdown_block_lines(markdown: str) -> list[str]:
        normalized = str(markdown).strip()
        if not normalized:
            return []
        return [line.rstrip() for line in normalized.splitlines()]

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

            signature = CrprMCPServer._runtime_helper_signature(helper)
            parameters = CrprMCPServer._runtime_helper_parameter_lines(helper)
            examples = CrprMCPServer._runtime_helper_example_calls(helper)
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
        lines.extend(CrprMCPServer._capability_kind_legend())
        lines.append("")
        if capability.description:
            lines.extend(["### Description", capability.description, ""])

        if capability.kind == "workflow":
            lines.extend(
                [
                    "### Arg Usage",
                    f"`{CrprMCPServer._workflow_arg_usage(capability.id, capability.arg_schema)}`",
                    "",
                ]
            )

        lines.extend(
            [
                "### Arguments",
            ]
        )
        argument_rows = CrprMCPServer._capability_argument_table_lines(capability)
        if argument_rows:
            lines.extend(argument_rows)
        else:
            lines.append("- (none)")

        lines.extend(
            [
                "### Examples",
            ]
        )
        cli_examples = CrprMCPServer._capability_cli_examples(capability)
        if cli_examples:
            lines.extend(cli_examples)
        else:
            lines.append("- (none)")

        lines.extend(
            [
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
                "### Expected Output Summary",
            ]
        )
        output_summary_lines = CrprMCPServer._expected_output_summary_lines(capability.expected_output_shape)
        if output_summary_lines:
            lines.extend(output_summary_lines)
        else:
            lines.extend(["Returns a JSON object.", "- (no documented fields)"])

        if runtime_helpers is not None:
            lines.extend(["", "### Runtime Helpers"])
            modules = allowed_runtime_modules or []
            lines.append("Allowed runtime modules:")
            if modules:
                lines.extend([f"- `{module}`" for module in modules])
            else:
                lines.append("- (none)")
            runtime_helper_markdown = CrprMCPServer._format_runtime_helper_list_markdown(
                runtime_helpers,
                include_header=False,
                include_policy=False,
                detailed=True,
                empty_message="No runtime helpers registered.",
            )
            lines.extend(["", *runtime_helper_markdown.splitlines()])
        return "\n".join(lines)

    @staticmethod
    def _workflow_arg_usage(workflow_id: str, arg_schema: dict[str, Any]) -> str:
        parts: list[str] = []
        for arg_name, schema in arg_schema.items():
            if not isinstance(arg_name, str):
                continue
            schema_dict = schema if isinstance(schema, dict) else {}
            flag = f"--{arg_name.replace('_', '-')}"
            value_type = str(schema_dict.get("type", "value")).strip().lower() or "value"
            value_fragment = f"<{value_type}>"
            if schema_dict.get("required"):
                parts.append(f"{flag} {value_fragment}")
            else:
                parts.append(f"[{flag} {value_fragment}]")
        suffix = f" {' '.join(parts)}" if parts else ""
        return f"{workflow_id}{suffix}"

    @staticmethod
    def _capability_argument_table_lines(capability: CapabilityDoc) -> list[str]:
        if not capability.arg_schema:
            return []

        lines = [
            "| Name | Type | Required | Default | Description |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]

        for arg_name, schema in capability.arg_schema.items():
            if not isinstance(arg_name, str):
                continue
            schema_dict = schema if isinstance(schema, dict) else {}
            arg_type = str(schema_dict.get("type", "any")).strip() or "any"
            required = "Yes" if schema_dict.get("required") else "No"
            default = "N/A"
            if "default" in schema_dict:
                default = f"`{CrprMCPServer._python_literal(schema_dict.get('default'))}`"
            description = str(schema_dict.get("description", "")).strip() or "N/A"
            display_name = arg_name
            if capability.kind == "workflow":
                display_name = f"--{arg_name.replace('_', '-')}"

            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{CrprMCPServer._markdown_cell(display_name)}`",
                        f"`{CrprMCPServer._markdown_cell(arg_type)}`",
                        required,
                        default,
                        CrprMCPServer._markdown_cell(description),
                    ]
                )
                + " |"
            )
        return lines

    @staticmethod
    def _capability_cli_examples(capability: CapabilityDoc) -> list[str]:
        lines: list[str] = []
        for index, example in enumerate(capability.examples, start=1):
            if not isinstance(example, dict):
                continue
            command = CrprMCPServer._example_to_cli_command(example)
            if not command:
                continue
            lines.append(f"{index}. `{command}`")
        return lines

    @staticmethod
    def _example_to_cli_command(example: dict[str, Any]) -> str:
        call_name = example.get("call")
        if not isinstance(call_name, str) or not call_name.strip():
            return ""

        args = example.get("args")
        if not isinstance(args, dict) or not args:
            return call_name.strip()

        parts = [call_name.strip()]
        for key, value in args.items():
            flag = f"--{str(key).replace('_', '-')}"
            parts.append(f"{flag} {CrprMCPServer._cli_value(value)}")
        return " ".join(parts)

    @staticmethod
    def _cli_value(value: Any) -> str:
        if isinstance(value, str):
            escaped = value.replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _expected_output_summary_lines(expected_output_shape: dict[str, Any]) -> list[str]:
        if not expected_output_shape:
            return []

        lines = ["Returns a JSON object with:"]
        for field_name, field_shape in expected_output_shape.items():
            if not isinstance(field_name, str):
                continue
            type_label = CrprMCPServer._shape_type_label(field_shape)
            lines.append(f"- `{field_name}`: {CrprMCPServer._output_field_summary(field_name, type_label)}")
        return lines

    @staticmethod
    def _shape_type_label(shape: Any) -> str:
        if isinstance(shape, str):
            return shape
        if isinstance(shape, dict):
            return "object"
        if isinstance(shape, list):
            return "list"
        return "any"

    @staticmethod
    def _output_field_summary(field_name: str, type_label: str) -> str:
        lower_name = field_name.strip().lower()
        if lower_name == "summary":
            return "High-level summary details."
        if lower_name == "files":
            return "List of file entries touched by the workflow."
        if lower_name in {"owner", "repo", "pr_number", "pr-number"}:
            return f"Echoed input identifier (type `{type_label}`)."
        if lower_name in {"success", "exit_code", "result_json", "safety_rejections"}:
            return f"Execution result field (type `{type_label}`)."
        return f"Field with type `{type_label}`."

    @staticmethod
    def _markdown_cell(text: str) -> str:
        return text.replace("|", "\\|")

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
            arg_type = CrprMCPServer._schema_type_to_python(schema.get("type"))
            if schema.get("required"):
                params.append(f"{arg_name}: {arg_type}")
                continue
            if "default" in schema:
                params.append(f"{arg_name}: {arg_type} = {CrprMCPServer._python_literal(schema.get('default'))}")
                continue
            params.append(f"{arg_name}: {arg_type} | None = None")

        return f"{call_name}({', '.join(params)}) -> Any"

    @staticmethod
    def _runtime_helper_parameter_lines(helper: RuntimeHelperDoc) -> list[str]:
        lines: list[str] = []
        for arg_name, arg_schema in helper.arg_schema.items():
            schema = arg_schema if isinstance(arg_schema, dict) else {}
            arg_type = CrprMCPServer._schema_type_to_python(schema.get("type"))
            required_text = "required" if schema.get("required") else "optional"
            description = str(schema.get("description", "")).strip()
            default = schema.get("default")

            detail_parts = [f"`{arg_name}` (`{arg_type}`, {required_text})"]
            if "default" in schema:
                detail_parts.append(f"default `{CrprMCPServer._python_literal(default)}`")
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

            call_args = ", ".join(f"{key}={CrprMCPServer._python_literal(value)}" for key, value in args.items())
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
