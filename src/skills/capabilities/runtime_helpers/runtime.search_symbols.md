---
id: runtime.search_symbols
doc_type: runtime_helper
order: 2
execution:
  call: runtime.zoekt_tools.search_symbols
  arg_schema:
    query:
      type: string
      required: true
    limit:
      type: integer
      required: false
---

--- list_capabilities ---
- Summary: Symbol-focused Zoekt search wrapper.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.search_symbols`
- Summary: Symbol-focused Zoekt search wrapper.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.zoekt_tools.search_symbols(query='UserController lang:python', limit=10)
```