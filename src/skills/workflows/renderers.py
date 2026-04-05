import pathlib
from typing import Any, Callable

from ...execution.models import ExecutionResult


def format_workflow_result_markdown(workflow_id: str, result: ExecutionResult) -> str:
    process_status = "success" if result.success else "failure"
    output_status = _infer_output_status(result)
    lines = [
        f"## Workflow: `{workflow_id}`",
        "",
        f"- Process status: `{process_status}`",
        f"- Output status: `{output_status}`",
        f"- Exit code: `{result.exit_code}`",
        f"- Timing (ms): `{result.timing_ms}`",
    ]

    if not result.success:
        if result.safety_rejections:
            lines.append(f"- Safety rejections: `{len(result.safety_rejections)}`")
            lines.extend([f"  - {rejection}" for rejection in result.safety_rejections])
        if result.stderr:
            lines.extend(["", "### Error", "```text", result.stderr, "```"])
        if result.stdout:
            lines.extend(["", "### Stdout", "```text", result.stdout, "```"])
        return "\n".join(lines)

    payload = result.result_json
    if payload is None:
        lines.extend(
            [
                "",
                "No structured workflow payload was produced.",
                "This means execution completed, but output parsing or marker contract failed.",
            ]
        )
        if result.stderr:
            lines.extend(["", "### Parser / Runtime Details", "```text", result.stderr, "```"])
        if result.stdout:
            lines.extend(["", "### Stdout", "```text", result.stdout, "```"])
        return "\n".join(lines)

    workflow_renderers: dict[str, Callable[[Any], list[str]]] = {
        "repo_discovery": _render_repo_discovery_result,
        "symbol_definition": _render_symbol_search_result,
        "symbol_usage": _render_symbol_usage_result,
        "file_context_reader": _render_file_context_result,
        "pr_impact_assessment": _render_pr_impact_assessment_result,
        "pr_cross_repo_overlap_candidates": _render_pr_cross_repo_overlap_candidates_result,
        "validate_contract_alignment": _render_validate_contract_alignment_result,
    }
    renderer = workflow_renderers.get(workflow_id, _render_generic_workflow_result)
    body = renderer(payload)

    if body:
        lines.extend(["", *body])
    if result.stderr:
        lines.extend(["", "### Stderr", "```text", result.stderr, "```"])
    if result.stdout:
        lines.extend(["", "### Stdout", "```text", result.stdout, "```"])
    return "\n".join(lines)


def _infer_output_status(result: ExecutionResult) -> str:
    if result.result_json is not None:
        return "parsed"

    stderr_lc = (result.stderr or "").lower()
    if "malformed result marker json" in stderr_lc:
        return "parse_error"
    if "result marker not found" in stderr_lc:
        return "missing_result_marker"
    if result.success:
        return "missing_payload"
    return "not_available"


def _render_repo_discovery_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    query = str(payload.get("query", "")).strip()
    repositories = payload.get("repositories") if isinstance(payload.get("repositories"), list) else []
    results = payload.get("results") if isinstance(payload.get("results"), list) else []

    lines = [
        f"Found `{len(repositories)}` repositories for `{query}`." if query else f"Found `{len(repositories)}` repositories.",
        "",
    ]
    if repositories:
        lines.append("### Repositories")
        lines.extend([f"{index}. `{repo}`" for index, repo in enumerate(repositories, start=1)])
    else:
        lines.append("No repositories found.")

    if results:
        lines.extend(["", "### Top Matches", *_render_search_results(results)])
    return lines


def _render_symbol_search_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    query = str(payload.get("query", "")).strip()
    total_hits = payload.get("total_hits", 0)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []

    lines = [f"Found `{total_hits}` matches for `{query}`." if query else f"Found `{total_hits}` matches.", ""]
    if results:
        lines.extend(_render_search_results(results))
    else:
        lines.append("No matches found.")
    return lines


def _render_symbol_usage_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    mode = str(payload.get("mode", "")).strip() or "unknown"
    attempted_queries = payload.get("attempted_queries") if isinstance(payload.get("attempted_queries"), list) else []
    total_queries = _coerce_int(payload.get("total_queries"), default=len(attempted_queries))
    total_raw_hits = _coerce_int(payload.get("total_raw_hits"), default=0)
    total_hits = _coerce_int(payload.get("total_hits"), default=0)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []

    lines = [
        f"Found `{total_hits}` deduplicated matches from `{total_queries}` Zoekt queries.",
        f"- Mode: `{mode}`",
        f"- Raw hits before dedup: `{total_raw_hits}`",
    ]

    if attempted_queries:
        lines.extend(["", "### Attempted Queries"])
        for index, entry in enumerate(attempted_queries[:12], start=1):
            if not isinstance(entry, dict):
                lines.append(f"{index}. `{_stringify_scalar(entry)}`")
                continue
            query = str(entry.get("query", "")).strip()
            label = str(entry.get("variant_label", "")).strip() or "query"
            hits = _coerce_int(entry.get("hits"), default=0)
            lines.append(f"{index}. `{label}` | `{hits}` hits | `{query}`")
        if len(attempted_queries) > 12:
            lines.append(f"... and `{len(attempted_queries) - 12}` more queries.")

    if results:
        lines.extend(["", "### Top Matches", *_render_search_results(results)])
    else:
        lines.extend(["", "No matches found."])
    return lines


def _render_file_context_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    source_owner = str(payload.get("source_owner", "")).strip()
    source_repo = str(payload.get("source_repo", "")).strip()
    repo = str(payload.get("repo", "")).strip()
    path = str(payload.get("path", "")).strip()
    start_line = _coerce_int(payload.get("start_line"), default=1)
    end_line = _coerce_int(payload.get("end_line"), default=start_line)
    content = str(payload.get("content", ""))
    evidence_origin = str(payload.get("evidence_origin", "")).strip() or "zoekt_index"

    header = (
        f"`{repo}/{path}` lines `{start_line}-{end_line}`" if repo and path else f"Lines `{start_line}-{end_line}`"
    )
    lines = [header, f"- Evidence origin: `{evidence_origin}`"]
    if source_owner and source_repo:
        lines.append(f"- Source PR repo: `{source_owner}/{source_repo}`")
    lines.append("")

    if not content:
        lines.append("No content returned for the requested range.")
        return lines

    language = _language_from_path(path)
    numbered_code = _with_line_numbers(content, start_line=start_line)
    lines.extend([f"```{language}", numbered_code, "```"])
    return lines


def _render_pr_impact_assessment_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    owner = str(payload.get("owner", "")).strip()
    repo = str(payload.get("repo", "")).strip()
    pr_number = _coerce_int(payload.get("pr_number"), default=0)
    pr = payload.get("pr") if isinstance(payload.get("pr"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    status_counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), list) else []
    directory_counts = payload.get("directory_counts") if isinstance(payload.get("directory_counts"), list) else []
    extension_summary = payload.get("extension_summary") if isinstance(payload.get("extension_summary"), list) else []
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    largest_files = payload.get("largest_files") if isinstance(payload.get("largest_files"), list) else []
    title = str(pr.get("title", "")).strip()

    lines = [
        f"PR `{owner}/{repo}#{pr_number}` impact assessment." if owner and repo else "PR impact assessment.",
        f"- Title: {title or '(untitled)'}",
        f"- Files changed: `{_coerce_int(totals.get('files_changed'), default=len(largest_files))}`",
        f"- Additions/Deletions: `{_coerce_int(totals.get('additions'), 0)}` / `{_coerce_int(totals.get('deletions'), 0)}`",
        f"- Compact file entries: `{len(files)}`",
    ]

    top_extensions = summary.get("top_extensions") if isinstance(summary.get("top_extensions"), list) else []
    if top_extensions:
        lines.extend(["", "### Top Extensions"])
        for entry in top_extensions[:8]:
            if isinstance(entry, dict):
                lines.append(f"- `{entry.get('name', '(unknown)')}`: `{_coerce_int(entry.get('count'), 0)}`")

    if status_counts:
        lines.extend(["", "### Status Mix"])
        for entry in status_counts[:8]:
            if isinstance(entry, dict):
                lines.append(f"- `{entry.get('status', '(unknown)')}`: `{_coerce_int(entry.get('count'), 0)}`")

    if directory_counts:
        lines.extend(["", "### Directories"])
        for entry in directory_counts[:10]:
            if isinstance(entry, dict):
                lines.append(f"- `{entry.get('directory', '(unknown)')}`: `{_coerce_int(entry.get('count'), 0)}`")

    if extension_summary:
        lines.extend(["", "### Extension Surface"])
        for entry in extension_summary[:10]:
            if not isinstance(entry, dict):
                continue
            extension = str(entry.get("extension", "(unknown)"))
            changes = _coerce_int(entry.get("changes"), 0)
            lines.append(f"- `{extension}`: `{changes}` changes")

    if largest_files:
        lines.extend(["", "### Largest File Deltas"])
        for entry in largest_files[:10]:
            if isinstance(entry, dict):
                filename = str(entry.get("filename", "(unknown)"))
                changes = _coerce_int(entry.get("changes"), 0)
                lines.append(f"- `{filename}`: `{changes}` changes")
    return lines


def _render_pr_cross_repo_overlap_candidates_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    owner = str(payload.get("owner", "")).strip()
    repo = str(payload.get("repo", "")).strip()
    pr_number = _coerce_int(payload.get("pr_number"), default=0)
    inspected_repo_count = _coerce_int(payload.get("inspected_repo_count"), default=0)
    overlap_candidates = (
        payload.get("overlap_candidates") if isinstance(payload.get("overlap_candidates"), list) else []
    )
    confirmed_conflicts = (
        payload.get("confirmed_conflicts") if isinstance(payload.get("confirmed_conflicts"), list) else []
    )
    no_confirmed_conflicts = bool(payload.get("no_confirmed_conflicts", False))
    no_confirmed_conflicts_reason = str(payload.get("no_confirmed_conflicts_reason", "")).strip()
    coverage_complete = bool(payload.get("coverage_complete", False))
    coverage_reason = str(payload.get("coverage_reason", "")).strip()
    required_followup_angles = (
        payload.get("required_followup_angles") if isinstance(payload.get("required_followup_angles"), list) else []
    )
    suggested_alignment_checks = (
        payload.get("suggested_alignment_checks")
        if isinstance(payload.get("suggested_alignment_checks"), list)
        else []
    )
    excluded_source_repos = (
        payload.get("excluded_source_repos") if isinstance(payload.get("excluded_source_repos"), list) else []
    )

    lines = [
        f"PR `{owner}/{repo}#{pr_number}` cross-repo overlap scan." if owner and repo else "Cross-repo overlap scan.",
        f"- Repositories inspected: `{inspected_repo_count}`",
        f"- Overlap candidates (unvalidated): `{len(overlap_candidates)}`",
        f"- Confirmed conflicts: `{len(confirmed_conflicts)}`",
        "- Candidate-only workflow: follow-up validation is required before a final no-conflict claim.",
    ]
    if no_confirmed_conflicts:
        lines.append(
            f"- No confirmed conflicts in this pass: `true` ({no_confirmed_conflicts_reason or 'no_reason_provided'})"
        )
    else:
        lines.append("- No confirmed conflicts in this pass: `false`")
    if coverage_complete:
        lines.append("- Coverage complete: `true`")
    else:
        lines.append(f"- Coverage complete: `false` ({coverage_reason or 'followup_required'})")
    if required_followup_angles:
        lines.append("- Required follow-up angles:")
        lines.extend([f"  - `{angle}`" for angle in required_followup_angles[:8]])
    lines.append(f"- Suggested alignment checks: `{len(suggested_alignment_checks)}`")
    if excluded_source_repos:
        lines.append("- Source repos excluded by default:")
        lines.extend([f"  - `{source_repo}`" for source_repo in excluded_source_repos[:5]])

    if confirmed_conflicts:
        lines.extend(["", "### Confirmed Conflicts"])
        for entry in confirmed_conflicts[:10]:
            if not isinstance(entry, dict):
                continue
            conflict_repo = str(entry.get("repo", "(unknown)"))
            total_hits = _coerce_int(entry.get("total_hits"), default=0)
            evidence_count = _coerce_int(entry.get("contract_evidence_count"), default=0)
            lines.append(
                f"- `{conflict_repo}`: `{evidence_count}` contract evidence samples (`{total_hits}` total overlap hits)"
            )

    if overlap_candidates:
        lines.extend(["", "### Top Overlap Candidate Repos (Unvalidated)"])
        for entry in overlap_candidates[:10]:
            if not isinstance(entry, dict):
                continue
            conflict_repo = str(entry.get("repo", "(unknown)"))
            total_hits = _coerce_int(entry.get("total_hits"), default=0)
            term_matches = entry.get("term_matches") if isinstance(entry.get("term_matches"), list) else []
            lines.append(f"- `{conflict_repo}`: `{total_hits}` total hits (`{len(term_matches)}` matched terms)")
        sample_hits = _collect_overlap_candidate_samples(overlap_candidates)
        if sample_hits:
            lines.extend(["", "### Candidate Sample Snippets", *_render_search_results(sample_hits, max_files=8)])
    else:
        lines.extend(["", "No cross-repo overlap candidates found."])

    if suggested_alignment_checks:
        lines.extend(["", "### Suggested Alignment Checks"])
        for index, check in enumerate(suggested_alignment_checks[:8], start=1):
            if not isinstance(check, dict):
                continue
            term = str(check.get("term", "")).strip() or "(unknown term)"
            command = _alignment_check_command_from_suggestion(check)
            lines.append(f"{index}. `{term}`")
            lines.append(f"   `{command}`")
    return lines


def _render_validate_contract_alignment_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    provider = payload.get("provider") if isinstance(payload.get("provider"), dict) else {}
    consumer = payload.get("consumer") if isinstance(payload.get("consumer"), dict) else {}
    alignment = payload.get("alignment") if isinstance(payload.get("alignment"), dict) else {}
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    coverage_complete = bool(payload.get("coverage_complete", False))
    coverage_reason = str(payload.get("coverage_reason", "")).strip() or "unknown"

    provider_label = f"{provider.get('owner', '')}/{provider.get('repo', '')}".strip("/")
    provider_path = str(provider.get("path", "")).strip()
    consumer_repo = str(consumer.get("repo", "")).strip()
    consumer_path = str(consumer.get("path", "")).strip()

    lines = [
        "Contract alignment assessment.",
        f"- Provider: `{provider_label}` `{provider_path}`",
        f"- Consumer: `{consumer_repo}` `{consumer_path}`",
        f"- Coverage complete: `{'true' if coverage_complete else 'false'}` ({coverage_reason})",
    ]

    if warnings:
        lines.extend(["", "### Warnings"])
        for warning in warnings[:10]:
            lines.append(f"- {warning}")

    if alignment:
        lines.extend(["", "### Alignment Diff"])
        for category in ("keys", "params", "http_signatures"):
            category_alignment = alignment.get(category)
            if not isinstance(category_alignment, dict):
                continue
            shared = category_alignment.get("shared") if isinstance(category_alignment.get("shared"), list) else []
            provider_only = (
                category_alignment.get("provider_only")
                if isinstance(category_alignment.get("provider_only"), list)
                else []
            )
            consumer_only = (
                category_alignment.get("consumer_only")
                if isinstance(category_alignment.get("consumer_only"), list)
                else []
            )
            lines.append(
                f"- `{category}`: shared `{len(shared)}`, provider-only `{len(provider_only)}`, consumer-only `{len(consumer_only)}`"
            )

    if findings:
        lines.extend(["", "### Findings"])
        for finding in findings[:12]:
            if not isinstance(finding, dict):
                continue
            category = str(finding.get("category", "overall"))
            kind = str(finding.get("kind", "unknown"))
            count = _coerce_int(finding.get("count"), 0)
            confidence = str(finding.get("confidence", "low"))
            lines.append(f"- `{category}` `{kind}`: `{count}` items (`{confidence}` confidence)")
    return lines


def _collect_overlap_candidate_samples(overlap_candidates: list[Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for candidate in overlap_candidates[:6]:
        if not isinstance(candidate, dict):
            continue
        repo = str(candidate.get("repo", "")).strip()
        term_matches = candidate.get("term_matches")
        if not isinstance(term_matches, list):
            continue
        for term_match in term_matches[:2]:
            if not isinstance(term_match, dict):
                continue
            samples_list = term_match.get("samples")
            if not isinstance(samples_list, list):
                continue
            for sample in samples_list[:1]:
                if not isinstance(sample, dict):
                    continue
                sample_repo = str(sample.get("repository", "")).strip() or repo
                filename = str(sample.get("filename", "")).strip()
                matches = sample.get("matches") if isinstance(sample.get("matches"), list) else []
                if not filename or not matches:
                    continue
                samples.append(
                    {
                        "repository": sample_repo,
                        "filename": filename,
                        "matches": matches,
                        "url": sample.get("url"),
                    }
                )
    return samples


def _alignment_check_command_from_suggestion(check: dict[str, Any]) -> str:
    command_parts = ["validate_contract_alignment"]
    arg_order = [
        "provider_path",
        "provider_start_line",
        "provider_end_line",
        "consumer_repo",
        "consumer_path",
        "consumer_start_line",
        "consumer_end_line",
    ]
    for arg_name in arg_order:
        if arg_name not in check:
            continue
        value = check.get(arg_name)
        if value is None:
            continue
        command_parts.append(f"--{arg_name.replace('_', '-')} {value}")
    return " ".join(command_parts)


def _render_generic_workflow_result(payload: Any) -> list[str]:
    if payload is None:
        return ["No structured workflow payload returned."]
    if isinstance(payload, (str, int, float, bool)):
        return [f"Result: `{payload}`"]
    if isinstance(payload, list):
        if not payload:
            return ["Result list is empty."]
        lines = [f"Result list with `{len(payload)}` items:"]
        for index, item in enumerate(payload[:10], start=1):
            lines.append(f"{index}. `{_stringify_scalar(item)}`")
        if len(payload) > 10:
            lines.append(f"... and `{len(payload) - 10}` more items.")
        return lines
    if isinstance(payload, dict):
        lines = ["Result fields:"]
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                lines.append(f"- `{key}`: `{value}`")
            elif isinstance(value, list):
                lines.append(f"- `{key}`: list with `{len(value)}` items")
            elif isinstance(value, dict):
                lines.append(f"- `{key}`: object with `{len(value)}` fields")
            else:
                lines.append(f"- `{key}`: `{type(value).__name__}`")
        return lines
    return [f"Result type: `{type(payload).__name__}`"]


def _render_search_results(results: list[Any], max_files: int = 10, max_matches_per_file: int = 3) -> list[str]:
    lines: list[str] = []
    for index, entry in enumerate(results[:max_files], start=1):
        if not isinstance(entry, dict):
            lines.append(f"{index}. `{_stringify_scalar(entry)}`")
            continue

        repository = str(entry.get("repository", "")).strip()
        filename = str(entry.get("filename", "")).strip()
        location = "/".join(part for part in [repository, filename] if part) or "(unknown location)"
        lines.append(f"{index}. `{location}`")

        matches = entry.get("matches") if isinstance(entry.get("matches"), list) else []
        if not matches:
            lines.append("```text")
            lines.append("(no match snippets)")
            lines.append("```")
        for match_index, match in enumerate(matches[:max_matches_per_file], start=1):
            if not isinstance(match, dict):
                lines.append("```text")
                lines.append(_stringify_scalar(match))
                lines.append("```")
                continue
            line_number = max(1, _coerce_int(match.get("line_number"), default=1))
            text = str(match.get("text", "")).rstrip()
            lines.append(f"Match `{match_index}` (anchor `L{line_number}`):")
            lines.append("```text")
            lines.append(_with_line_numbers(text, start_line=line_number) if text else "(empty snippet)")
            lines.append("```")

        if len(matches) > max_matches_per_file:
            lines.append(f"... `{len(matches) - max_matches_per_file}` additional matches omitted")

        url = str(entry.get("url", "")).strip()
        if url:
            lines.append(url)

    if len(results) > max_files:
        lines.append(f"... and `{len(results) - max_files}` more files.")
    return lines


def _indent_markdown(lines: list[str], spaces: int = 2) -> list[str]:
    prefix = " " * spaces
    return [f"{prefix}{line}" if line else "" for line in lines]


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stringify_scalar(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    return type(value).__name__


def _with_line_numbers(content: str, start_line: int) -> str:
    lines = content.splitlines()
    if not lines:
        return ""
    max_line = start_line + len(lines) - 1
    width = max(2, len(str(max_line)))
    return "\n".join(f"{line_no:>{width}} | {line}" for line_no, line in enumerate(lines, start=start_line))


def _language_from_path(path: str) -> str:
    suffix = pathlib.Path(path).suffix.lower()
    mapping = {
        ".py": "python",
        ".ts": "ts",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".rs": "rust",
        ".c": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".sh": "bash",
        ".sql": "sql",
        ".html": "html",
        ".css": "css",
    }
    return mapping.get(suffix, "text")
