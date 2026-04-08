---
id: run_workflow_cli
doc_type: tool
---

Execute a prebuilt workflow by CLI-style command.
Parameters:
- Read capability for allowed commands and arg schemas `read_capability(capability_id="execution.run_workflow_cli")`.
Output:
- Markdown text with workflow-specific rendering (not raw JSON dumps).
- Includes both `Process status` and `Output status` so execution vs parse/render issues are explicit.
- Search-style workflows render concise match lists with line numbers.
- File-context workflow renders a code block with line numbers.
