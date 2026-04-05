import asyncio
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..skills.registry import SkillRegistry
from .models import ExecutionResult
from .safety import validate_custom_workflow_code

RESULT_MARKER = "__RESULT_JSON__="
TIMEOUT_EXIT_CODE = 124
_ENV_ALLOWLIST = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "TZ",
    "ZOEKT_API_URL",
}


class ExecutionRunner:
    def __init__(
        self,
        src_root: Path,
        skills_root: Path,
        timeout_default: int,
        timeout_max: int,
        stdout_max_bytes: int,
        stderr_max_bytes: int,
        github_rpc_url: str = "http://127.0.0.1:8080/internal/github-rpc",
    ) -> None:
        self.src_root = src_root
        self.skills_root = skills_root
        self.timeout_default = timeout_default
        self.timeout_max = timeout_max
        self.stdout_max_bytes = stdout_max_bytes
        self.stderr_max_bytes = stderr_max_bytes
        self.github_rpc_url = str(github_rpc_url).strip() or "http://127.0.0.1:8080/internal/github-rpc"
        self._workflow_index = self._load_workflows()

    def _load_workflows(self) -> dict[str, dict[str, Any]]:
        registry = SkillRegistry(self.skills_root)
        workflow_index: dict[str, dict[str, Any]] = {}

        for capability in registry.capabilities.values():
            if capability.kind != "workflow":
                continue
            if not capability.script_path:
                raise ValueError(f"workflow capability missing execution.script_path: {capability.id}")
            workflow_index[capability.id] = {
                "id": capability.id,
                "script_path": capability.script_path,
                "arg_schema": capability.arg_schema,
            }

        return workflow_index

    def parse_workflow_cli_command(self, command: str) -> tuple[str, dict[str, Any]]:
        original_command = command.strip()
        if not original_command:
            raise ValueError("args validation failure: command must not be empty")

        tokens = self._parse_cli_tokens(original_command)

        if not tokens:
            raise ValueError("args validation failure: command must not be empty")

        workflow_id = tokens[0]
        workflow = self._workflow_index.get(workflow_id)
        if workflow is None:
            available = ", ".join(sorted(self._workflow_index))
            raise ValueError(
                f"args validation failure: unknown workflow_id: {workflow_id}. Available workflows: {available}"
            )

        arg_schema = workflow.get("arg_schema")
        if not isinstance(arg_schema, dict):
            arg_schema = {}

        usage = self._workflow_usage(workflow_id, arg_schema)
        flag_aliases = self._workflow_flag_aliases(arg_schema)
        parsed_args: dict[str, Any] = {}

        index = 1
        while index < len(tokens):
            token = tokens[index]
            if not token.startswith("--"):
                hint = self._escaped_quotes_hint(tokens=tokens, command=original_command)
                if hint:
                    raise ValueError(f"args validation failure: unexpected positional argument `{token}`. {usage} {hint}")
                raise ValueError(f"args validation failure: unexpected positional argument `{token}`. {usage}")

            arg_name = flag_aliases.get(token)
            if arg_name is None:
                raise ValueError(f"args validation failure: unknown flag `{token}`. {usage}")
            if arg_name in parsed_args:
                raise ValueError(f"args validation failure: duplicate flag `{token}`. {usage}")
            if index + 1 >= len(tokens):
                raise ValueError(f"args validation failure: missing value for `{token}`. {usage}")

            value_token = tokens[index + 1]
            if value_token.startswith("--"):
                raise ValueError(f"args validation failure: missing value for `{token}`. {usage}")

            schema = arg_schema.get(arg_name)
            if not isinstance(schema, dict):
                schema = {"type": "string"}
            parsed_args[arg_name] = self._coerce_cli_arg_value(arg_name, value_token, schema, usage)
            index += 2

        for arg_name, schema in arg_schema.items():
            if arg_name in parsed_args:
                continue
            if not isinstance(schema, dict) or "default" not in schema:
                continue
            parsed_args[arg_name] = self._coerce_cli_arg_value(arg_name, schema["default"], schema, usage)

        missing = [
            arg_name
            for arg_name, schema in arg_schema.items()
            if isinstance(schema, dict) and schema.get("required") and arg_name not in parsed_args
        ]
        if missing:
            missing_flags = ", ".join(f"--{arg_name.replace('_', '-')}" for arg_name in missing)
            raise ValueError(f"args validation failure: missing required flags: {missing_flags}. {usage}")

        return workflow_id, parsed_args

    @staticmethod
    def _parse_cli_tokens(command: str) -> list[str]:
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError as exc:
            normalized = ExecutionRunner._normalize_over_escaped_quotes(command)
            if normalized != command:
                try:
                    return shlex.split(normalized, posix=True)
                except ValueError:
                    pass
                hint = (
                    " Hint: over-escaped quotes (`\\\"`) can break CLI parsing. "
                    "Use plain quotes, for example: --raw-query 'addToPantry r:checkout'."
                )
                raise ValueError(f"args validation failure: invalid command: {exc}.{hint}") from exc
            raise ValueError(f"args validation failure: invalid command: {exc}") from exc

        if ExecutionRunner._looks_like_over_escaped_quote_issue(tokens=tokens, command=command):
            normalized = ExecutionRunner._normalize_over_escaped_quotes(command)
            if normalized != command:
                try:
                    return shlex.split(normalized, posix=True)
                except ValueError:
                    pass

        return tokens

    @staticmethod
    def _normalize_over_escaped_quotes(command: str) -> str:
        return command.replace('\\"', '"')

    @staticmethod
    def _looks_like_over_escaped_quote_issue(tokens: list[str], command: str) -> bool:
        if '\\"' not in command:
            return False
        return any(
            not token.startswith("--") and (token.startswith('"') or token.endswith('"'))
            for token in tokens[1:]
        )

    @staticmethod
    def _escaped_quotes_hint(tokens: list[str], command: str) -> str | None:
        if not ExecutionRunner._looks_like_over_escaped_quote_issue(tokens=tokens, command=command):
            return None
        return (
            "Hint: value appears split by over-escaped quotes (`\\\"`). "
            "Use plain quotes, for example: --raw-query 'addToPantry r:checkout'."
        )

    async def run_workflow_cli_command(self, command: str, timeout_seconds: int) -> tuple[str, ExecutionResult]:
        workflow_id, args = self.parse_workflow_cli_command(command)
        result = await self.run_workflow_script(
            workflow_id=workflow_id,
            args=args,
            timeout_seconds=timeout_seconds,
        )
        return workflow_id, result

    async def run_workflow_script(
        self,
        workflow_id: str,
        args: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        workflow = self._workflow_index.get(workflow_id)
        if workflow is None:
            return self._error_result(message=f"unknown workflow_id: {workflow_id}", exit_code=2)

        arg_validation_error = self._validate_required_args(workflow, args)
        if arg_validation_error is not None:
            return self._error_result(message=arg_validation_error, exit_code=2)

        script_rel_path = workflow.get("script_path")
        if not isinstance(script_rel_path, str) or not script_rel_path:
            return self._error_result(message=f"workflow script_path missing: {workflow_id}", exit_code=2)

        script_path = self.src_root / script_rel_path
        if not script_path.exists():
            return self._error_result(message=f"workflow script missing: {script_path}", exit_code=2)

        with tempfile.TemporaryDirectory(prefix=f"zoekt-workflow-{workflow_id}-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            temp_script_path = temp_dir / "workflow_script.py"
            runtime_src = self.src_root / "runtime"
            runtime_dst = temp_dir / "runtime"

            shutil.copy2(script_path, temp_script_path)
            shutil.copytree(runtime_src, runtime_dst, dirs_exist_ok=True)

            command = self._build_isolated_command(temp_script_path, args)

            try:
                return await self._execute(command=command, cwd=temp_dir, timeout_seconds=timeout_seconds)
            finally:
                if temp_script_path.exists():
                    temp_script_path.unlink()

    async def run_custom_workflow_code(
        self,
        code: str,
        timeout_seconds: int,
    ) -> ExecutionResult:
        rejections = validate_custom_workflow_code(code)
        if rejections:
            return ExecutionResult(
                success=False,
                exit_code=1,
                stderr="custom workflow code rejected by safety policy",
                safety_rejections=rejections,
            )

        with tempfile.TemporaryDirectory(prefix="zoekt-custom-workflow-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            script_path = temp_dir / "custom_workflow_code.py"
            runtime_src = self.src_root / "runtime"
            runtime_dst = temp_dir / "runtime"

            script_path.write_text(code, encoding="utf-8")
            shutil.copytree(runtime_src, runtime_dst, dirs_exist_ok=True)

            command = self._build_custom_workflow_command(script_path)

            try:
                return await self._execute(
                    command=command,
                    cwd=temp_dir,
                    timeout_seconds=timeout_seconds,
                    require_result_marker=False,
                    allow_plain_stdout_result=True,
                )
            finally:
                if script_path.exists():
                    script_path.unlink()

    async def _execute(
        self,
        command: list[str],
        cwd: Path,
        timeout_seconds: int,
        require_result_marker: bool = True,
        allow_plain_stdout_result: bool = False,
    ) -> ExecutionResult:
        normalized_timeout = self._normalize_timeout(timeout_seconds)
        start = time.monotonic()

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                env=self._build_environment(
                    github_rpc_url=self.github_rpc_url,
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=normalized_timeout)
            except asyncio.TimeoutError:
                process.kill()
                stdout_bytes, stderr_bytes = await process.communicate()
                stdout = self._decode_and_cap(stdout_bytes, self.stdout_max_bytes, "stdout")
                stderr = self._decode_and_cap(stderr_bytes, self.stderr_max_bytes, "stderr")
                return ExecutionResult(
                    success=False,
                    exit_code=TIMEOUT_EXIT_CODE,
                    stdout=stdout,
                    stderr=(stderr + "\nexecution timed out" if stderr else "execution timed out"),
                    timing_ms=self._elapsed_ms(start),
                )
        except Exception as exc:
            return self._error_result(
                message=f"runner failed to start subprocess: {exc}",
                exit_code=70,
                timing_ms=self._elapsed_ms(start),
            )

        full_stdout = self._decode_lossy(stdout_bytes)
        full_stderr = self._decode_lossy(stderr_bytes)
        cleaned_stdout_full, result_json, parse_error, marker_found = self._extract_result_json(full_stdout)
        if result_json is None and allow_plain_stdout_result:
            result_json = self._coerce_plain_stdout_result(cleaned_stdout_full)
        stdout = self._cap_text(cleaned_stdout_full, self.stdout_max_bytes, "stdout")
        stderr = self._cap_text(full_stderr, self.stderr_max_bytes, "stderr")

        if require_result_marker and not marker_found and result_json is None:
            marker_error = "result marker not found"
            stderr = f"{stderr}\n{marker_error}" if stderr else marker_error
        if parse_error:
            stderr = f"{stderr}\n{parse_error}" if stderr else parse_error

        exit_code = int(process.returncode or 0)
        return ExecutionResult(
            success=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            result_json=result_json,
            timing_ms=self._elapsed_ms(start),
        )

    def _normalize_timeout(self, timeout_seconds: int) -> int:
        if timeout_seconds <= 0:
            return self.timeout_default
        return min(timeout_seconds, self.timeout_max)

    def _validate_required_args(self, workflow: dict[str, Any], args: dict[str, Any]) -> str | None:
        arg_schema = workflow.get("arg_schema", {})
        missing = [
            arg_name
            for arg_name, schema in arg_schema.items()
            if isinstance(schema, dict) and schema.get("required") and arg_name not in args
        ]
        if missing:
            missing_csv = ", ".join(sorted(missing))
            return f"args validation failure: missing required args: {missing_csv}"
        return None

    @staticmethod
    def _workflow_flag_aliases(arg_schema: dict[str, Any]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for arg_name in arg_schema.keys():
            if not isinstance(arg_name, str):
                continue
            aliases[f"--{arg_name}"] = arg_name
            aliases[f"--{arg_name.replace('_', '-')}"] = arg_name
        return aliases

    @staticmethod
    def _workflow_usage(workflow_id: str, arg_schema: dict[str, Any]) -> str:
        parts: list[str] = []
        for arg_name, schema in arg_schema.items():
            if not isinstance(arg_name, str):
                continue
            flag = f"--{arg_name.replace('_', '-')}"
            is_required = isinstance(schema, dict) and bool(schema.get("required"))
            fragment = f"{flag} <value>" if is_required else f"[{flag} <value>]"
            parts.append(fragment)
        suffix = f" {' '.join(parts)}" if parts else ""
        return f"Usage: {workflow_id}{suffix}"

    @staticmethod
    def _coerce_cli_arg_value(arg_name: str, raw_value: Any, schema: dict[str, Any], usage: str) -> Any:
        arg_type = str(schema.get("type", "string")).strip().lower()
        if arg_type == "string":
            return str(raw_value)
        if arg_type == "integer":
            try:
                value = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"args validation failure: invalid integer for `--{arg_name.replace('_', '-')}`: {raw_value!r}. {usage}"
                ) from exc
            minimum = ExecutionRunner._coerce_integer_bound(schema.get("minimum"))
            if minimum is not None and value < minimum:
                raise ValueError(
                    f"args validation failure: `--{arg_name.replace('_', '-')}` must be >= {minimum}: {value!r}. {usage}"
                )
            maximum = ExecutionRunner._coerce_integer_bound(schema.get("maximum"))
            if maximum is not None and value > maximum:
                raise ValueError(
                    f"args validation failure: `--{arg_name.replace('_', '-')}` must be <= {maximum}: {value!r}. {usage}"
                )
            return value
        if arg_type == "boolean":
            value = str(raw_value).strip().lower()
            if value in {"true", "1", "yes", "on"}:
                return True
            if value in {"false", "0", "no", "off"}:
                return False
            raise ValueError(
                f"args validation failure: invalid boolean for `--{arg_name.replace('_', '-')}`: {raw_value!r}. {usage}"
            )
        raise ValueError(
            f"args validation failure: unsupported arg type `{arg_type}` for `--{arg_name.replace('_', '-')}`. {usage}"
        )

    @staticmethod
    def _coerce_integer_bound(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _build_environment(self, github_rpc_url: str) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in _ENV_ALLOWLIST:
            value = os.environ.get(key)
            if value:
                env[key] = value
        env["CRPR_GITHUB_RPC_URL"] = github_rpc_url
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    @staticmethod
    def _build_isolated_command(script_path: Path, args: dict[str, Any]) -> list[str]:
        script = str(script_path)
        script_parent = str(script_path.parent)
        argv_tokens = ExecutionRunner._build_cli_argv_tokens(args)
        bootstrap = (
            "import runpy,sys;"
            f"script={script!r};"
            f"sys.path.insert(0,{script_parent!r});"
            f"argv={argv_tokens!r};"
            "sys.argv=[script,*argv];"
            "runpy.run_path(script, run_name='__main__')"
        )
        return [sys.executable, "-I", "-u", "-c", bootstrap]

    @staticmethod
    def _build_cli_argv_tokens(args: dict[str, Any]) -> list[str]:
        argv: list[str] = []
        for arg_name in sorted(args.keys()):
            argv.append(f"--{arg_name.replace('_', '-')}")
            argv.append(ExecutionRunner._serialize_cli_value(args[arg_name]))
        return argv

    @staticmethod
    def _serialize_cli_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (str, int, float)):
            return str(value)
        if value is None:
            return ""
        return json.dumps(value, ensure_ascii=True)

    @staticmethod
    def _build_custom_workflow_command(script_path: Path) -> list[str]:
        script = str(script_path)
        script_parent = str(script_path.parent)
        bootstrap = (
            "import runpy\n"
            "import sys\n"
            f"script = {script!r}\n"
            f"sys.path.insert(0, {script_parent!r})\n"
            "sys.argv = [script]\n"
            "runpy.run_path(script, run_name='__main__')\n"
        )
        return [sys.executable, "-I", "-u", "-c", bootstrap]

    @staticmethod
    def _decode_and_cap(raw: bytes, max_bytes: int, stream_name: str) -> str:
        if len(raw) <= max_bytes:
            return raw.decode("utf-8", errors="replace")

        capped = raw[:max_bytes].decode("utf-8", errors="replace")
        return f"{capped}\n[{stream_name} truncated at {max_bytes} bytes]"

    @staticmethod
    def _decode_lossy(raw: bytes) -> str:
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _cap_text(value: str, max_bytes: int, stream_name: str) -> str:
        raw = value.encode("utf-8", errors="replace")
        if len(raw) <= max_bytes:
            return value
        capped = raw[:max_bytes].decode("utf-8", errors="replace")
        return f"{capped}\n[{stream_name} truncated at {max_bytes} bytes]"

    @staticmethod
    def _extract_result_json(stdout: str) -> tuple[str, Any, str | None, bool]:
        lines = stdout.splitlines()
        for index in range(len(lines) - 1, -1, -1):
            line = lines[index]
            if not line.startswith(RESULT_MARKER):
                continue

            payload = line[len(RESULT_MARKER) :]
            cleaned_lines = lines[:index] + lines[index + 1 :]
            cleaned_stdout = "\n".join(cleaned_lines)

            try:
                return cleaned_stdout, json.loads(payload), None, True
            except json.JSONDecodeError as exc:
                return cleaned_stdout, None, f"malformed result marker JSON: {exc.msg}", True

        stripped = stdout.strip()
        if stripped:
            try:
                return "", json.loads(stripped), None, False
            except json.JSONDecodeError:
                pass

        return stdout, None, None, False

    @staticmethod
    def _coerce_plain_stdout_result(stdout: str) -> Any:
        stripped = stdout.strip()
        if not stripped:
            return None

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    @staticmethod
    def _error_result(message: str, exit_code: int, timing_ms: int = 0) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            exit_code=exit_code,
            stderr=message,
            timing_ms=timing_ms,
        )
