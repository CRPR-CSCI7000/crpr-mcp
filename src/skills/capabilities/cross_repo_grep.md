---
id: cross_repo_grep
doc_type: capability
kind: workflow
order: 5
execution:
  script_path: skills/workflows/scripts/cross_repo_grep.py
  arg_schema:
    regexp:
      type: string
      required: true
      position: 1
      aliases: ["-e"]
      description: Search pattern (regex by default). Positional `PATTERN` is also accepted.
    path:
      type: string
      required: false
      position: 2
      description: Optional Zoekt `f:` path filter (single file, directory prefix, or regex-like pattern).
    repo:
      type: string
      required: false
      aliases: ["-r"]
      description: Optional repository filter (`r:<repo>`). Omit to search across indexed repositories in current context.
    ignore_case:
      type: boolean
      required: false
      default: false
      aliases: ["-i"]
      description: Case-insensitive matching.
    fixed_strings:
      type: boolean
      required: false
      default: false
      aliases: ["-F"]
      description: Treat pattern as a literal string instead of regex.
    word_regexp:
      type: boolean
      required: false
      default: false
      aliases: ["-w"]
      description: Match only whole-word occurrences.
    line_number:
      type: boolean
      required: false
      default: false
      aliases: ["-n"]
      description: Preserve explicit line-number mode in output metadata.
    before_context:
      type: integer
      required: false
      default: 0
      minimum: 0
      aliases: ["-B"]
      description: Show this many lines before each match.
    after_context:
      type: integer
      required: false
      default: 0
      minimum: 0
      aliases: ["-A"]
      description: Show this many lines after each match.
    context_lines:
      type: integer
      required: false
      default: 0
      minimum: 0
      maximum: 50
      aliases: ["-C"]
      description: Shorthand to set both before/after context line counts.
    max_count:
      type: integer
      required: false
      default: 25
      minimum: 1
      aliases: ["-m"]
      description: Maximum matches to return.
---

--- list_capabilities ---
- Kind: `workflow`
- Summary: grep/rg-style pattern search across files in the scoped Zoekt snapshot.
- When to use: Use when you need anchors for a symbol/term across a repo, then drill in with `file_context_reader`.
- Next step: `read_capability(capability_id="cross_repo_grep")`
- Interface details intentionally omitted here; use `read_capability`.

--- read_capability ---
## Capability: `cross_repo_grep`

- Kind: `workflow`

### Capability Types
- `workflow`: prebuilt analysis flows invoked with `run_workflow_cli`.
- `execution_pattern`: guidance capabilities for execution interfaces (prefix `execution.*`).

### Description
Searches for a pattern across repository files in the PR-scoped Zoekt snapshot.
Interface style is a hybrid: familiar grep/rg-style flags (`-i`, `-F`, `-w`, `-n`, `-A/-B/-C`, `-m`) with Zoekt-backed repository/path scoping.

### Arg Usage
{{ARG_USAGE}}

### Arguments
{{ARG_TABLE}}
### Examples
1. `cross_repo_grep "enqueue_invoice_event"`
2. `cross_repo_grep -n -C 5 -i "enqueue_invoice_event" src/billing`
3. `cross_repo_grep -F -m 10 "enqueueInvoice(" --repo github.com/acme/ui --path src/actions`
### Constraints
- Default scope is all indexed repositories in the current context when `--repo` is omitted.
- Positional form is `cross_repo_grep [OPTIONS] PATTERN [PATH_FILTER]`.
- `max_count` hard-clamped to 250.
- Context values are bounded to 50 lines.
- For downstream breakage triage, start by targeting runtime consumer code paths (handlers/routes/services/components/parsers) first.
- Prefer queries that show runtime read/map behavior of changed fields before query passes over schema/reference artifacts.
- Do not treat zero hits from one exact pattern as proof of no downstream consumers.
- If no exact hits: retry with variant token forms (snake/camel/kebab/plural), retry with contract-surface tokens (route/event/topic/payload/schema names), and relax overly narrow `--path` filters.
- Prefer multiple targeted grep passes over one broad natural-language phrase.

### Expected Output Summary
Returns markdown to the agent; key structured fields in that output include:
{{EXPECTED_OUTPUT_SUMMARY}}
