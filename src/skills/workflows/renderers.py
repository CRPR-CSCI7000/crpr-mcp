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
        f"Found `{len(repositories)}` repositories for `{query}`."
        if query
        else f"Found `{len(repositories)}` repositories.",
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
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []

    header = f"`{repo}/{path}` lines `{start_line}-{end_line}`" if repo and path else f"Lines `{start_line}-{end_line}`"
    lines = [header, f"- Evidence origin: `{evidence_origin}`"]
    if source_owner and source_repo:
        lines.append(f"- Source PR repo: `{source_owner}/{source_repo}`")
    if warnings:
        lines.append(f"- Warnings: `{len(warnings)}`")
    lines.append("")

    if warnings:
        lines.append("### Warnings")
        for warning in warnings[:10]:
            lines.append(f"- {warning}")
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

    removed_top = [
        entry
        for entry in largest_files
        if isinstance(entry, dict) and str(entry.get("status", "")).strip().lower() == "removed"
    ]
    if removed_top:
        lines.extend(["", "### Notable Removals"])
        for entry in removed_top[:5]:
            filename = str(entry.get("filename", "(unknown)"))
            changes = _coerce_int(entry.get("changes"), 0)
            lines.append(f"- `{filename}`: `{changes}` changes")

    renamed_top = [
        entry
        for entry in largest_files
        if isinstance(entry, dict) and str(entry.get("status", "")).strip().lower() == "renamed"
    ]
    if renamed_top:
        lines.extend(["", "### Notable Renames"])
        for entry in renamed_top[:5]:
            filename = str(entry.get("filename", "(unknown)"))
            previous = str(entry.get("previous_filename", "")).strip()
            changes = _coerce_int(entry.get("changes"), 0)
            if previous:
                lines.append(f"- `{previous}` -> `{filename}`: `{changes}` changes")
            else:
                lines.append(f"- `{filename}`: `{changes}` changes")
    return lines


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
