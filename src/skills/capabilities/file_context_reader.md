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
      description: Target repository identifier (must not equal source repo).
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
- Summary: Read a bounded line window from a non-source repository file (never source PR files).
- When to use: Use only after you identify a specific non-source repo file to inspect; never use for source PR files or changed-file validation.
- Scope warning: never use this for source PR repository files; use `pr_file_context_reader`.
- Next step: `read_capability(capability_id="file_context_reader")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `file_context_reader`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Reads a specific line range from a file in a non-source repository via Zoekt.
In PR-scoped analysis this workflow is cross-repo only; source repository reads are rejected.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `file_context_reader --repo github.com/acme/inventory --path src/service.py --start-line 40 --end-line 85`
### Constraints
- Source-repo reads are blocked; use `pr_file_context_reader` for source PR repository content.
- Requires a file path, not a directory.
- Hard limit: requested window (`end_line - start_line + 1`) must be <= 60 lines.
- Prefer iterative narrow reads over broad file grabs.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
