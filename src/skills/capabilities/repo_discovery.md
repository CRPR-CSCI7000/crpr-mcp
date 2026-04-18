---
id: repo_discovery
doc_type: capability
kind: workflow
order: 1
execution:
  script_path: skills/workflows/scripts/repo_discovery.py
  arg_schema:
    repo_prefix:
      type: string
      required: false
      description: Optional repository-name prefix filter (for example `pantry_pal` or `github.com/acme/pantry_pal`).
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Discover repositories from indexed repository names.
- When to use: Start here when you need a short ranked list of candidate repositories before symbol/file workflows.
- Next step: `read_capability(capability_id="repo_discovery")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `repo_discovery`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Runs repository discovery against indexed repository names with optional repository-name prefix filtering (`repo_prefix`).

### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `repo_discovery --repo-prefix 'pantry_pal'`
2. `repo_discovery --repo-prefix 'github.com/acme/pantry'`
3. `repo_discovery`  # returns all indexed repos in current context
### Constraints
- `repo_prefix` is optional.
- If `repo_prefix` is omitted, returns all indexed repositories in current Zoekt context.
- File-level include/exclude filters are intentionally not supported in this workflow.
- Returns repository candidates and hit counts; it does not return file-context snippets.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
