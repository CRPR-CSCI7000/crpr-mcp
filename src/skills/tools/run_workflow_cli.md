---
id: run_workflow_cli
doc_type: tool
---

Execute a prebuilt workflow by CLI-style command.
Prefer this path over generated scripts whenever a matching workflow exists. For PR-scoped analysis, start with `pr_impact_assessment` first. Then use `symbol_definition`/`symbol_usage` for focused lookups. For `symbol_usage`, prefer structured filters (`--term` with `--repo`/`--lang`/`--path`); use `--raw-query` only for direct Zoekt syntax and `--expand-variants true` only when exact terms miss call sites. Use `pr_file_context_reader` for source-repo reads (PR head/base SHA), and use `file_context_reader` only for cross-repo Zoekt reads. Hard limits: search context lines must be <= 10; file windows must be <= 60 lines.
Parameters: - command (required): CLI form `<workflow_id> [--flag value]...`
Output: - Markdown text with workflow-specific rendering (not raw JSON dumps). - Includes both `Process status` and `Output status` so execution vs parse/render issues are explicit. - Search-style workflows render concise match lists with line numbers. - File-context workflow renders a code block with line numbers.
