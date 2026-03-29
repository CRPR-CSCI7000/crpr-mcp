---
id: runtime.github_get_file_content
doc_type: runtime_helper
order: 8
execution:
  call: runtime.github_tools.get_file_content
  arg_schema:
    owner:
      type: string
      required: true
    repo:
      type: string
      required: true
    path:
      type: string
      required: true
    ref:
      type: string
      required: false
---

--- list_capabilities ---
- Summary: Fetch file content from GitHub repository at an optional ref.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.github_get_file_content`
- Summary: Fetch file content from GitHub repository at an optional ref.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.github_tools.get_file_content(owner='acme', repo='checkout', path='src/service.py', ref='2f4d9d0')
```