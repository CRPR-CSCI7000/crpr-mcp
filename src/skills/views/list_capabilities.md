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
- For source PR files (including changed files), use `pr_file_context_reader`.
- `file_context_reader` is cross-repo only; source-repo reads are rejected.

{{DISCOVERY_ITEMS}}
