---
id: runtime.github_get_pull_request
doc_type: runtime_helper
order: 6
execution:
  call: runtime.github_tools.get_pull_request
  arg_schema: {}
---

--- list_capabilities ---
- Summary: Fetch GitHub pull request metadata.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.github_get_pull_request`
- Summary: Fetch GitHub pull request metadata.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.github_tools.get_pull_request()
```
- Notes:
- Requires thread-scoped PR context (`CRPR_CONTEXT_OWNER`, `CRPR_CONTEXT_REPO`, `CRPR_CONTEXT_PR_NUMBER`) in subprocess env.
