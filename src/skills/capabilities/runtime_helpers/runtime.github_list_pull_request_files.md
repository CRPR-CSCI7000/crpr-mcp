---
id: runtime.github_list_pull_request_files
doc_type: runtime_helper
order: 7
execution:
  call: runtime.github_tools.list_pull_request_files
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
- Summary: Fetch complete GitHub pull request file list.
- Details: use `read_capability(capability_id="execution.run_custom_workflow_code")`

--- read_capability ---
#### `runtime.github_list_pull_request_files`
- Summary: Fetch complete GitHub pull request file list.
- Signature:
```python
{{RUNTIME_SIGNATURE}}
```
- Parameters:
{{RUNTIME_PARAMETERS}}
- Examples:
```python
runtime.github_tools.list_pull_request_files(owner='acme', repo='checkout', pr_number=123)
```