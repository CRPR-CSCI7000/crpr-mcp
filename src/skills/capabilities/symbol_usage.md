---
id: symbol_usage
doc_type: capability
kind: workflow
order: 3
execution:
  script_path: skills/workflows/scripts/symbol_usage.py
  arg_schema:
    term:
      type: string
      required: true
      description: Usage term for structured query composition.
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
      description: Maximum number of deduplicated result groups returned.
    context_lines:
      type: integer
      required: false
      default: 5
      minimum: 0
      maximum: 10
      description: Context lines around each match.
    expand_variants:
      type: boolean
      required: false
      default: false
      description: Expand term into deterministic casing/plural variants.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Locate call-sites with structured Zoekt filters.
- When to use: Use after definitions are known and before reading file ranges directly.
- Next step: `read_capability(capability_id="symbol_usage")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `symbol_usage`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Runs structured Zoekt usage search by building a query from `term` and optional filters.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `symbol_usage --term enqueueInvoice --repo github.com/acme/ui --lang javascript --path src/actions --exclude-path test --limit 8 --context-lines 5`
2. `symbol_usage --term /user --repo github.com/acme/ui --expand-variants true --limit 8`
### Constraints
- `term` is required.
- For definitions use `symbol_definition` instead.
- Prefer this workflow to narrow targets before `file_context_reader`.
- `context_lines` is hard-limited to 10.
- Do not treat zero hits for one exact term as proof of no usage.
- If exact term returns no hits, run follow-up searches with `expand_variants=true` and with contract tokens (routes, event names, queue/topic keys, payload field names, schema/type identifiers).
- Use `repo`/`path` filters to narrow noise, but relax overly strict filters when investigating possible downstream consumers.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
