---
id: execution.run_custom_workflow_code
doc_type: capability
kind: execution_pattern
order: 10
execution:
  arg_schema:
    code:
      type: string
      required: true
---

--- list_capabilities ---
- Kind: `execution_pattern`
- Summary: Fallback path for one-off tasks not covered by workflows.
- When to use: Use only when no prebuilt workflow can satisfy the task, and only after calling read_capability for this id to confirm constraints.
- Next step: `read_capability(capability_id="execution.run_custom_workflow_code")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `execution.run_custom_workflow_code`

- Kind: `execution_pattern`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Execute generated code after AST safety checks in an isolated subprocess.
Code is executed directly as a script (`__main__`).
Runtime helper details are provided in `read_capability(execution.run_custom_workflow_code)`.
Use self-contained code and emit output via stdout:
plain text, plain JSON, or `__RESULT_JSON__=<json>` marker (optional).

### Runtime Helpers
{{RUNTIME_HELPERS_SECTION}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `run_custom_workflow_code(code="import json
from runtime import github_tools

pr = github_tools.get_pull_request()
print(json.dumps({\"title\": pr.get(\"title\", \"\")}, ensure_ascii=True))
")`
### Constraints
- Import policy: custom code may import only approved modules from the safety allowlist. Use runtime helpers via `from runtime import zoekt_tools, github_tools`, `import runtime.zoekt_tools as zoekt_tools`, or `import runtime.github_tools as github_tools`.

- Any other imports and banned calls are rejected before execution.
- For best structured outputs, print JSON or marker JSON; plain text stdout is also accepted.
- This is process-level isolation, not container-grade sandboxing.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
- `success`: Execution result field (type `boolean`).
- `exit_code`: Execution result field (type `integer`).
- `safety_rejections`: Execution result field (type `list[string]`).
- `result_json`: Execution result field (type `object|null`).
