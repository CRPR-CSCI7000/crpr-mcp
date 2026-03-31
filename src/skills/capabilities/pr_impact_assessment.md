---
id: pr_impact_assessment
doc_type: capability
kind: workflow
order: 6
execution:
  script_path: skills/workflows/scripts/pr_impact_assessment.py
  arg_schema: {}
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Build source PR metadata, compact files, and change-surface impact in one workflow.
- When to use: Use first for pull-request scoped impact discovery before overlap and validation workflows.
- Next step: `read_capability(capability_id="pr_impact_assessment")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `pr_impact_assessment`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Retrieves PR metadata and changed files from GitHub, then computes compact file summaries and
impact aggregates (status mix, directories, extensions, and largest deltas) in one response.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `pr_impact_assessment`
### Constraints
- Returns compact file metadata and impact aggregates, not full patches.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
