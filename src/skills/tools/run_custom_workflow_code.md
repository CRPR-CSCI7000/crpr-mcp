---
id: run_custom_workflow_code
doc_type: tool
---

Execute generated custom workflow code in an isolated subprocess after AST safety checks.
Use only when no prebuilt workflow can satisfy the task. Before using this tool, read `execution.run_custom_workflow_code` via `read_capability`. Runtime helper listing is available via `list_capabilities(view="runtime_helpers")`.
Required script constraints: - generated code must be self-contained and executable as a script - import policy allows only approved modules; rely on `read_capability` for the current allowlist and runtime helper details - runtime helper calls can be used directly; no event-loop boilerplate is required for normal helper usage
Parameters: - code (required): Python source code - timeout_seconds (optional): execution timeout
Output format: - Markdown text with execution status and fenced sections for result_json/stdout/stderr. - Custom code may return output by printing plain text, printing JSON, or printing marker JSON.
