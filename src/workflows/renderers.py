import pathlib
from typing import Any, Callable

from ..execution.models import ExecutionResult


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
        "symbol_usage": _render_symbol_search_result,
        "file_context_reader": _render_file_context_result,
        "pr_file_context_reader": _render_pr_file_context_result,
        "pr_context_summary": _render_pr_context_summary_result,
        "pr_change_surface": _render_pr_change_surface_result,
        "pr_cross_repo_overlap_candidates": _render_pr_cross_repo_overlap_candidates_result,
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


def _render_pr_file_context_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    owner = str(payload.get("owner", "")).strip()
    repo = str(payload.get("repo", "")).strip()
    pr_number = _coerce_int(payload.get("pr_number"), default=0)
    path = str(payload.get("path", "")).strip()
    start_line = _coerce_int(payload.get("start_line"), default=1)
    end_line = _coerce_int(payload.get("end_line"), default=start_line)
    content = str(payload.get("content", ""))
    ref_side = str(payload.get("ref_side", "")).strip() or "head"
    ref_name = str(payload.get("ref_name", "")).strip()
    ref_sha = str(payload.get("ref_sha", "")).strip()
    evidence_origin = str(payload.get("evidence_origin", "")).strip() or f"github_pr_{ref_side}"

    target = f"{owner}/{repo}" if owner and repo else "(unknown repo)"
    header = f"`{target}` PR `#{pr_number}` `{path}` lines `{start_line}-{end_line}`"
    lines = [
        header,
        f"- Evidence origin: `{evidence_origin}`",
        f"- Ref side/name: `{ref_side}` / `{ref_name or '(unknown)'}`",
        f"- Ref SHA: `{ref_sha or '(unknown)'}`",
        "",
    ]

    if not content:
        lines.append("No content returned for the requested range.")
        return lines

    language = _language_from_path(path)
    numbered_code = _with_line_numbers(content, start_line=start_line)
    lines.extend([f"```{language}", numbered_code, "```"])
    return lines


def _render_pr_context_summary_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    owner = str(payload.get("owner", "")).strip()
    repo = str(payload.get("repo", "")).strip()
    pr_number = _coerce_int(payload.get("pr_number"), default=0)
    pr = payload.get("pr") if isinstance(payload.get("pr"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    files = payload.get("files") if isinstance(payload.get("files"), list) else []

    title = str(pr.get("title", "")).strip()
    changed_files = _coerce_int(pr.get("changed_files"), default=len(files))
    additions = _coerce_int(pr.get("additions"), default=0)
    deletions = _coerce_int(pr.get("deletions"), default=0)

    lines = [
        f"PR `{owner}/{repo}#{pr_number}` context summary." if owner and repo else "PR context summary.",
        f"- Title: {title or '(untitled)'}",
        f"- Changed files: `{changed_files}`",
        f"- Additions/Deletions: `{additions}` / `{deletions}`",
    ]

    top_extensions = summary.get("top_extensions") if isinstance(summary.get("top_extensions"), list) else []
    if top_extensions:
        lines.extend(["", "### Top Extensions"])
        for entry in top_extensions[:8]:
            if isinstance(entry, dict):
                lines.append(f"- `{entry.get('name', '(unknown)')}`: `{_coerce_int(entry.get('count'), 0)}`")

    top_directories = summary.get("top_directories") if isinstance(summary.get("top_directories"), list) else []
    if top_directories:
        lines.extend(["", "### Top Directories"])
        for entry in top_directories[:8]:
            if isinstance(entry, dict):
                lines.append(f"- `{entry.get('name', '(unknown)')}`: `{_coerce_int(entry.get('count'), 0)}`")
    return lines


def _render_pr_change_surface_result(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return _render_generic_workflow_result(payload)

    owner = str(payload.get("owner", "")).strip()
    repo = str(payload.get("repo", "")).strip()
    pr_number = _coerce_int(payload.get("pr_number"), default=0)
    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    status_counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), list) else []
    directory_counts = payload.get("directory_counts") if isinstance(payload.get("directory_counts"), list) else []
    largest_files = payload.get("largest_files") if isinstance(payload.get("largest_files"), list) else []

    lines = [
        f"PR `{owner}/{repo}#{pr_number}` change surface." if owner and repo else "PR change surface.",
        f"- Files changed: `{_coerce_int(totals.get('files_changed'), default=len(largest_files))}`",
        f"- Additions/Deletions: `{_coerce_int(totals.get('additions'), 0)}` / `{_coerce_int(totals.get('deletions'), 0)}`",
    ]

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
    excluded_source_repos = (
        payload.get("excluded_source_repos") if isinstance(payload.get("excluded_source_repos"), list) else []
    )

    lines = [
        f"PR `{owner}/{repo}#{pr_number}` cross-repo overlap scan." if owner and repo else "Cross-repo overlap scan.",
        f"- Repositories inspected: `{inspected_repo_count}`",
        f"- Overlap candidates (unvalidated): `{len(overlap_candidates)}`",
        f"- Confirmed conflicts: `{len(confirmed_conflicts)}`",
    ]
    if no_confirmed_conflicts:
        lines.append(f"- No confirmed conflicts: `true` ({no_confirmed_conflicts_reason or 'no_reason_provided'})")
    else:
        lines.append("- No confirmed conflicts: `false`")
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
    else:
        lines.extend(["", "No cross-repo overlap candidates found."])
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


def _render_search_results(results: list[Any], max_files: int = 10, max_matches_per_file: int = 4) -> list[str]:
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
        for match in matches[:max_matches_per_file]:
            if not isinstance(match, dict):
                lines.append(f"   - `{_stringify_scalar(match)}`")
                continue
            line_number = _coerce_int(match.get("line_number"), default=0)
            text = str(match.get("text", "")).replace("\n", " ").strip()
            if len(text) > 220:
                text = f"{text[:217]}..."
            lines.append(f"   - L{line_number}: `{text}`")

        if len(matches) > max_matches_per_file:
            lines.append(f"   - ... `{len(matches) - max_matches_per_file}` more matches")

        url = str(entry.get("url", "")).strip()
        if url:
            lines.append(f"   {url}")

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
