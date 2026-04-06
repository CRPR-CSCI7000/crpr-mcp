# CRPR MCP Server

`crpr-mcp` is a Model Context Protocol (MCP) server that exposes a workflow-first interface for Zoekt-backed code intelligence.

## Architecture

Single service/process with embedded modules:

- `capabilities/`: capability discovery and full capability docs
- `execution/`: request/result models, AST safety checks, and isolated runner
- `workflows/`: workflow manifest and prebuilt scripts
- `runtime/zoekt_tools.py`: safe Python wrappers over Zoekt HTTP endpoints
- `runtime/github_tools.py`: subprocess-safe wrappers that call parent-owned GitHub RPC on internal FastMCP route

There is no separate executor service.

## MCP Tools (Breaking Change)

The server exposes only these 4 tools:

1. `list_capabilities(view: Literal["capabilities", "runtime_helpers"] = "capabilities")`
2. `read_capability(capability_id: str)`
3. `run_workflow_cli(command: str, timeout_seconds: int = 30)`
4. `run_custom_workflow_code(code: str, timeout_seconds: int = 30)`

All tool responses are rendered as markdown text for agent readability.

## Recommended Flow

1. Call `list_capabilities`.
2. Call `read_capability` for selected ids.
3. Prefer `run_workflow_cli` for known tasks.
4. For custom code, optionally call `list_capabilities(view="runtime_helpers")`.
5. Use `run_custom_workflow_code` only when workflows do not fit.

`run_workflow_cli` command format:

- `<workflow_id> [--flag value]...`
- Example: `symbol_usage --term addToPantry --repo github.com/acme/ui --lang javascript --limit 8 --context-lines 1`

## Custom Workflow Code Constraints

Generated scripts are AST-validated before execution:

- Script should be self-contained top-level Python code.
- Import policy allows only approved modules from the safety allowlist.
- Runtime helpers are available via
  `from runtime import zoekt_tools, github_tools`,
  `import runtime.zoekt_tools as zoekt_tools`, or
  `import runtime.github_tools as github_tools`.
- Banned imports include modules such as `os`, `subprocess`, `socket`, `ctypes`, `multiprocessing`, `pathlib`
- Banned calls include `eval`, `exec`, `compile`, `open`, `__import__`, `input`

## Execution Behavior

- Every run executes in an isolated temp working directory.
- Subprocess invocation uses `python -I -u`.
- Environment is reduced to an allowlist.
- GitHub API calls are parent-owned via local RPC; subprocesses do not receive GitHub PAT/App secrets.
- Timeout and stdout/stderr caps are enforced.
- Result payload is parsed from stdout:
  - plain JSON stdout -> parsed JSON result
  - plain text stdout -> string result
  - marker output `__RESULT_JSON__=<json>` is also accepted

This is process-level sandboxing, not container-grade isolation.

## Configuration

Required:

- `ZOEKT_API_URL`

Required for GitHub-backed PR workflows (GitHub App preferred, PAT fallback):

- GitHub App (preferred)
  - `GITHUB_APP_ID`
  - `GITHUB_APP_INSTALLATION_ID`

- `GITHUB_TOKEN` (PAT fallback when GitHub App auth is not configured or fails)
  - Used by workflows such as `pr_impact_assessment`.
  - Token should have access to the repositories being analyzed.

Optional:

- `MCP_SSE_PORT` (default `8000`)
- `MCP_STREAMABLE_HTTP_PORT` (default `8080`)
- `EXECUTION_TIMEOUT_SECONDS` (default `300`)
- `EXECUTION_STDOUT_MAX_BYTES` (default `32768`)
- `EXECUTION_STDERR_MAX_BYTES` (default `32768`)

## Local Dev

Create local env file and set GitHub auth if you use PR workflows:

```bash
cp src/.env.sample src/.env
# edit src/.env and set GitHub App values or GITHUB_TOKEN
```

```bash
uv sync
uv run python src/main.py
```

Lint:

```bash
uv run ruff check src
```
