---
id: symbol_definition
doc_type: capability
kind: workflow
order: 2
execution:
  script_path: skills/workflows/scripts/symbol_definition.py
  arg_schema:
    query:
      type: string
      required: true
      description: Symbol query, optionally with filters (repo/lang/etc).
    limit:
      type: integer
      required: false
      default: 10
      description: Maximum number of hits.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Find likely symbol definitions across repositories.
- When to use: Use when you need where a class/function/type is defined.
- Next step: `read_capability(capability_id="symbol_definition")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `symbol_definition`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Uses symbol-focused search to locate likely definition sites for a named symbol.
Supports passing additional Zoekt filters inside `query` (for example repo/lang filters).


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `symbol_definition --query 'PaymentService lang:python'`
### Constraints
- Focused on definitions, not general usages.
- Prefer adding `lang:` and `r:` filters for precision.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
