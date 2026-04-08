---
id: symbol_definition
doc_type: capability
kind: workflow
order: 2
execution:
  script_path: skills/workflows/scripts/symbol_definition.py
  arg_schema:
    term:
      type: string
      required: true
      description: Symbol term for structured definition query composition.
    repo:
      type: string
      required: false
      description: Repository filter mapped to `r:<repo>`.
    lang:
      type: string
      required: false
      description: Language filter mapped to `lang:<lang>`.
    path:
      type: string
      required: false
      description: Path include filter mapped to `f:<path>`.
    exclude_path:
      type: string
      required: false
      description: Path exclude filter mapped to `-f:<path>`.
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
Builds a structured query from `term` and optional Zoekt filters.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `symbol_definition --term PaymentService --lang python`
2. `symbol_definition --term ProcessOrder --repo github.com/acme/checkout --path src/services --exclude-path test --limit 8`
### Constraints
- Focused on definitions, not general usages.
- Structured mode only; raw query passthrough is not supported.
- Prefer adding `lang` and `repo` filters for precision.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
