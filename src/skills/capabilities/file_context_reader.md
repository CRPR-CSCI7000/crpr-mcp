---
id: file_context_reader
doc_type: capability
kind: workflow
order: 4
execution:
  script_path: skills/workflows/scripts/file_context_reader.py
  arg_schema:
    repo:
      type: string
      required: true
      description: Target repository identifier in Zoekt context scope.
    path:
      type: string
      required: true
      description: File path inside repository.
    start_line:
      type: integer
      required: true
      minimum: 1
      description: 1-indexed start line.
    end_line:
      type: integer
      required: true
      minimum: 1
      description: 1-indexed end line.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Read a bounded line window from any repository file in the scoped Zoekt context.
- When to use: Use after you identify a specific source or cross-repo file path to inspect in the PR-scoped snapshot.
- Next step: `read_capability(capability_id="file_context_reader")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `file_context_reader`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Reads a specific line range from a file via Zoekt using the active PR-scoped context.
Works for both source-repo and cross-repo files present in the context snapshot.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `file_context_reader --repo github.com/acme/inventory --path src/service.py --start-line 40 --end-line 85`
### Constraints
- Requires a file path, not a directory.
- Include owner and repo for reliability: `<owner>/<repo>` or `github.com/<owner>/<repo>`.
- Bare repo names (for example `billing_api_service`) may fail in PR-scoped contexts.
- Hard limit: requested window (`end_line - start_line + 1`) must be <= 60 lines.
- Prefer iterative narrow reads over broad file grabs.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
