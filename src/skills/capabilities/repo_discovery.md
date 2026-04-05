---
id: repo_discovery
doc_type: capability
kind: workflow
order: 1
execution:
  script_path: skills/workflows/scripts/repo_discovery.py
  arg_schema:
    query:
      type: string
      required: true
      description: Free-form intent or component keywords used to discover candidate repos.
    limit:
      type: integer
      required: false
      default: 10
      description: Maximum search results to request.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Discover relevant repositories for a topic or component.
- When to use: Start here when you do not know which repos likely contain the target code.
- Next step: `read_capability(capability_id="repo_discovery")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `repo_discovery`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Discover candidate repositories for an objective by running a repository-focused Zoekt search.
This workflow transforms the objective into a `type:repo` query and returns ranked repository names.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `repo_discovery --query 'auth token refresh' --limit 12`
### Constraints
- Keep `limit` small (5-15) for focused discovery.
- Uses Zoekt repository search mode (`type:repo`).

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
