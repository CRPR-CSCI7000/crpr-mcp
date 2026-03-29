---
id: runtime.fetch_content
doc_type: runtime_helper
order: 3
execution:
  call: runtime.zoekt_tools.fetch_content
  arg_schema:
    repo:
      type: string
      required: true
    path:
      type: string
      required: true
    start_line:
      type: integer
      required: true
    end_line:
      type: integer
      required: true
---

--- list_capabilities ---
- Summary: Fetch a bounded file content range.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.fetch_content`
- Summary: Fetch a bounded file content range.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.zoekt_tools.fetch_content(repo='github.com/org/repo', path='src/main.go', start_line=1, end_line=60)
```