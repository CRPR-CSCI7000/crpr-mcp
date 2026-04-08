---
id: run_custom_workflow_code
doc_type: tool
---

Execute generated custom workflow code in an isolated subprocess after AST safety checks.
Parameters:
- Read capability for import allowlist, runtime helpers, and constraints `read_capability(capability_id="execution.run_custom_workflow_code")`.
Output format:
- Markdown text with execution status and fenced sections for `result_json`/`stdout`/`stderr`.
- Custom code may return output by printing plain text, printing JSON, or printing marker JSON.
