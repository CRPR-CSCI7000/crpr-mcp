---
id: pr_file_context_reader
doc_type: capability
kind: workflow
order: 5
execution:
  script_path: skills/workflows/scripts/pr_file_context_reader.py
  arg_schema:
    path:
      type: string
      required: true
      description: File path inside source repository.
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
    ref_side:
      type: string
      required: false
      default: head
      description: PR ref side to read from (`head` or `base`).
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Read source PR repository file lines pinned to PR head/base SHA.
- When to use: Use for source-repo evidence in PR-scoped analysis, including changed files in the source PR.
- Scope note: use this for source PR file reads at `head`/`base` refs.
- Next step: `read_capability(capability_id="pr_file_context_reader")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `pr_file_context_reader`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Reads a specific line range from a source-repo file using GitHub content at PR `head` or `base` SHA.
This avoids branch/index ambiguity when evaluating source PR changes.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `pr_file_context_reader --path src/service.py --start-line 20 --end-line 60 --ref-side head`
2. `pr_file_context_reader --path src/service.py --start-line 20 --end-line 60 --ref-side base`
### Constraints
- Uses GitHub PR metadata and repository contents API.
- Hard limit: requested window (`end_line - start_line + 1`) must be <= 60 lines.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
