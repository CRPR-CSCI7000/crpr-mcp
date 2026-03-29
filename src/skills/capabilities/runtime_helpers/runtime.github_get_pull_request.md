---
id: runtime.github_get_pull_request
doc_type: runtime_helper
order: 6
execution:
  call: runtime.github_tools.get_pull_request
  arg_schema:
    owner:
      type: string
      required: true
    repo:
      type: string
      required: true
    pr_number:
      type: integer
      required: true
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
runtime.github_tools.get_pull_request(owner='acme', repo='checkout', pr_number=123)
```