---
id: runtime.list_dir
doc_type: runtime_helper
order: 4
execution:
  call: runtime.zoekt_tools.list_dir
  arg_schema:
    repo:
      type: string
      required: true
    path:
      type: string
      required: false
    depth:
      type: integer
      required: false
---

--- list_capabilities ---
- Summary: List directory tree for repository path.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.list_dir`
- Summary: List directory tree for repository path.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.zoekt_tools.list_dir(repo='github.com/org/repo', path='src', depth=2)
```