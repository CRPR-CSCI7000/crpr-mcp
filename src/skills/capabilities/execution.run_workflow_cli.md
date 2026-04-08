---
id: execution.run_workflow_cli
doc_type: capability
kind: execution_pattern
order: 9
execution:
  arg_schema:
    command:
      type: string
      required: true
---

--- list_capabilities ---
- Kind: `execution_pattern`
- Summary: Preferred path for repeatable analysis tasks.
- When to use: Use when a prebuilt workflow already fits the objective.
- Next step: `read_capability(capability_id="execution.run_workflow_cli")`
- Recommended execution flow:
1. Run `pr_impact_assessment` first to collect PR metadata and changed-file scope.
2. Run `file_context_reader` for changed files to validate source repo evidence and extract contract surface (endpoints, handlers, schemas).
3. Run `repo_discovery` to identify candidate repositories for cross-repo contract tracing.
4. Run `symbol_definition` to anchor likely declaration sites for target handlers/types/functions.
5. Run `symbol_usage` to map call-sites and propagation paths across repos using those anchored symbols.
6. Run `file_context_reader` on the exact matched ranges to validate concrete source/cross-repo evidence.
> Note: this is a recommended flow, not a prescriptive sequence. Be creative. Always adapt to the specific PR context and emerging findings.

--- read_capability ---
## Capability: `execution.run_workflow_cli`

- Kind: `execution_pattern`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Execute a prebuilt workflow script via CLI-style command flags.

### Arguments
{{ARG_TABLE}}
### Examples
1. `run_workflow_cli(command="symbol_definition --term ProcessOrder --lang go")`
### Constraints
- Always call `read_capability` for the specific workflow id before execution.
- Prefer this before generating custom workflow code.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
- `success`: Execution result field (type `boolean`).
- `exit_code`: Execution result field (type `integer`).
- `result_json`: Execution result field (type `object|null`).
