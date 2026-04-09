---
id: repo_discovery
doc_type: capability
kind: workflow
order: 1
execution:
  script_path: skills/workflows/scripts/repo_discovery.py
  arg_schema:
    term:
      type: string
      required: false
      description: Optional content-search token(s) used in `type:repo` discovery queries.
    repo_prefix:
      type: string
      required: false
      description: Optional repository-name prefix filter (for example `pantry_pal` or `github.com/acme/pantry_pal`).
    limit:
      type: integer
      required: false
      default: 10
      description: Maximum repository candidates to request.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Discover repositories from a Zoekt query.
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
Runs structured Zoekt repository discovery using optional content tokens (`term`) and optional repository-name prefix filtering (`repo_prefix`).
Treat `term` as lexical code/search tokens (identifiers, route fragments, event/topic names, payload fields), not natural-language intent phrases.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `repo_discovery --term 'enqueue_invoice_event invoice_routes' --limit 12`
2. `repo_discovery --repo-prefix 'pantry_pal'`
3. `repo_discovery --term 'enqueue_invoice_event' --repo-prefix 'github.com/acme/pantry' --limit 10`
4. `repo_discovery`  # returns all indexed repos in current context
### Constraints
- `term` and `repo_prefix` are both optional.
- If `term` is omitted (and only prefix/listing behavior is used), the workflow resolves repositories from the indexed repo list rather than content hits.
- If both `term` and `repo_prefix` are omitted, returns all indexed repositories in current Zoekt context.
- `limit` applies to term-based content search mode; list/prefix-only mode returns all matching indexed repositories.
- File-level include/exclude filters are intentionally not supported in this workflow.
- Returns repository candidates and hit counts; it does not return file-context snippets.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
