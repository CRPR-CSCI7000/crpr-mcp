---
id: validate_contract_alignment
doc_type: capability
kind: workflow
order: 8
execution:
  script_path: skills/workflows/scripts/validate_contract_alignment.py
  arg_schema:
    provider_path:
      type: string
      required: true
      description: Provider-side file path in the source repository.
    provider_start_line:
      type: integer
      required: true
      minimum: 1
      description: Provider-side 1-indexed start line.
    provider_end_line:
      type: integer
      required: true
      minimum: 1
      description: Provider-side 1-indexed end line.
    consumer_repo:
      type: string
      required: true
      description: Consumer repository identifier in Zoekt.
    consumer_path:
      type: string
      required: true
      description: Consumer-side file path in the indexed repository.
    consumer_start_line:
      type: integer
      required: true
      minimum: 1
      description: Consumer-side 1-indexed start line.
    consumer_end_line:
      type: integer
      required: true
      minimum: 1
      description: Consumer-side 1-indexed end line.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: Heuristically compare provider and consumer contract signals across repo boundaries.
- When to use: Use after overlap discovery to validate provider-vs-consumer drift in focused file ranges.
- Next step: `read_capability(capability_id="validate_contract_alignment")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `validate_contract_alignment`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Fetches provider content from the source repo and consumer content from a scoped indexed file range
via Zoekt, then compares extracted keys, parameters, and HTTP signatures.
Returns structured drift findings with coverage warnings when extraction is sparse.


### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `validate_contract_alignment --provider-path api/contracts/order.json --provider-start-line 1 --provider-end-line 60 --consumer-repo github.com/acme/web --consumer-path src/api/orderClient.ts --consumer-start-line 40 --consumer-end-line 90`
### Constraints
- Provider and consumer reads are Zoekt-backed and must target indexed repositories.
- Hard limit: each requested line window must be <= 60 lines.
- Heuristic extraction can be partial; use `coverage_complete` and warnings to calibrate confidence.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
