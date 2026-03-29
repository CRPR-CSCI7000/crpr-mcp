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
      required: false
      description: Usage term for structured mode query composition.
    raw_query:
      type: string
      required: false
      description: Raw Zoekt query for direct execution (bypasses structured mode).
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
      description: Expand term into deterministic casing/plural variants (structured mode
        only).
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Locate call-sites with Zoekt-native structured filters or raw query override.
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
Runs Zoekt usage search in one of two modes:
- structured mode: build query from `term` and optional Zoekt filters.
- raw mode: pass `raw_query` directly.
Exactly one of `term` or `raw_query` is required.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `run_workflow_cli --command "symbol_usage --term addToPantry --repo github.com/acme/ui --lang javascript --path src/actions --exclude-path test --limit 8 --context-lines 5"`
2. `run_workflow_cli --command "symbol_usage --term add_to_pantry --repo github.com/acme/ui --expand-variants true --limit 8"`
3. `run_workflow_cli --command "symbol_usage --raw-query 'r:github.com/acme/ui addToPantry lang:javascript -f:test' --limit 8 --context-lines 1"`
### Constraints
- Exactly one of `term` or `raw_query` is required.
- Raw mode rejects structured-only flags (`repo`, `lang`, `path`, `exclude_path`, `expand_variants`).
- For definitions use `symbol_definition` instead.
- Prefer this workflow to narrow targets before `pr_file_context_reader` or `file_context_reader`.
- `context_lines` is hard-limited to 10.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
