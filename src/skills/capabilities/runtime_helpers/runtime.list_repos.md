---
id: runtime.list_repos
doc_type: runtime_helper
order: 5
execution:
  call: runtime.zoekt_tools.list_repos
  arg_schema: {}
---

--- list_capabilities ---
- Summary: List all indexed repositories.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.list_repos`
- Summary: List all indexed repositories.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.zoekt_tools.list_repos()
```