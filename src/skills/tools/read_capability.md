---
id: read_capability
doc_type: tool
---

Read the full capability document for one capability id.
Use this immediately after `list_capabilities` to confirm argument schema, constraints, examples, and expected output shape before execution. For `execution.run_custom_workflow_code`, this also includes embedded runtime-helper docs.
Parameters: - capability_id (required): capability id from `list_capabilities`
Output format: - Markdown text with CLI usage, argument tables, constraints, and concise output summaries.
