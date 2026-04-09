---
id: views.list_capabilities
doc_type: view
---

--- list_capabilities ---
## Capability List

- Total: `{{ total }}`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Discovery Policy
- Always call `read_capability` before using any capability from this list.
- `list_capabilities` is intentionally brief and omits arg schemas/examples/constraints.
- Do not execute capabilities from list output alone; use `read_capability` first.
- Use `file_context_reader` for most source/cross-repo file reads in scoped Zoekt context.
- Use `cross_repo_grep` when you need grep-style pattern anchors across a repo (optionally narrowed by path).

> No-hit policy: do not conclude "no downstream consumers" after one exact-symbol miss. Re-run with variant spellings and contract-surface terms (endpoint paths, event topics, payload field names, queue/topic names, schema/type names), then re-check candidate repos before concluding no evidence.

{{DISCOVERY_ITEMS}}

### Recommended execution flow:
1. Run the pre-scoped `pr_impact_assessment` first to collect PR metadata and changed-file scope.
2. Run `file_context_reader` on the anchored ranges to validate source repo evidence and extract contract surface changes (endpoints, handlers, schemas).
3. Summarize any PR-based contract surface changes and use that to guide the next steps.
4. Run `repo_discovery` to identify candidate repositories for cross-repo contract tracing.
5. Run `symbol_definition`, `symbol_usage`, or `cross_repo_grep` to identify where the impacted contract surface (handlers, endpoints, schemas, event topics, queue/topic keys) is declared and used across all other repos.
8. Run `file_context_reader` on the exact matched ranges to validate concrete source/cross-repo evidence.
