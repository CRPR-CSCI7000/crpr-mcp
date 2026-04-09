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
- When to use: Use when a prebuilt workflow already fits the task.
- Next step: `read_capability(capability_id="execution.run_workflow_cli")`

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
- Negative evidence rule: an exact-name miss is weak evidence only. Treat "no downstream consumers found" as valid only after at least one variant-based search pass and one contract-token search pass across candidate repos.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
- `success`: Execution result field (type `boolean`).
- `exit_code`: Execution result field (type `integer`).
- `result_json`: Execution result field (type `object|null`).
