---
id: runtime.search
doc_type: runtime_helper
order: 1
execution:
  call: runtime.zoekt_tools.search
  arg_schema:
    query:
      type: string
      required: true
    limit:
      type: integer
      required: false
    context_lines:
      type: integer
      required: false
---

--- list_capabilities ---
- Summary: General Zoekt content search wrapper.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.search`
- Summary: General Zoekt content search wrapper.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.zoekt_tools.search(query='error handler lang:python', limit=8, context_lines=1)
```