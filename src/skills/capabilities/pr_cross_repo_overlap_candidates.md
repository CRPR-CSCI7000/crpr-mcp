---
id: pr_cross_repo_overlap_candidates
doc_type: capability
kind: workflow
order: 7
execution:
  script_path: skills/workflows/scripts/pr_cross_repo_overlap_candidates.py
  arg_schema:
    include_source_repo:
      type: boolean
      required: false
      default: false
      description: Include canonical source repo in scanning.
    max_repos:
      type: integer
      required: false
      default: 0
      minimum: 0
      description: Optional cap on scanned repositories. 0 scans all indexed repos.
    per_term_limit:
      type: integer
      required: false
      default: 3
      minimum: 1
      description: Max Zoekt hits captured per term/repo query.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Find lexical overlap candidates for cross-repo contract checks.
- When to use: Use for candidate generation after `pr_impact_assessment`.
- Next step: `read_capability(capability_id="pr_cross_repo_overlap_candidates")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `pr_cross_repo_overlap_candidates`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Uses PR changed-file terms to probe indexed repositories for lexical overlap candidates.
By default, all indexed repositories are scanned and the canonical source repo is excluded.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `run_workflow_cli --command "pr_cross_repo_overlap_candidates"`
2. `run_workflow_cli --command "pr_cross_repo_overlap_candidates --include-source-repo true"`
### Constraints
- Defaults to all indexed repositories.
- Canonical source repo is excluded by default unless `include_source_repo=true`.
- Heuristic candidate detector; overlap hits are not confirmed contract conflicts.
- Candidate-generation step only; never use as final no-conflict clearance.
- Always follow up with targeted workflows before reporting concrete cross-repo risk.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
