import argparse
import asyncio
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from runtime import context as runtime_context
from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="
DEFAULT_MAX_COUNT = 25
MAX_MAX_COUNT = 250
MAX_CONTEXT_LINES = 50
MAX_SEARCH_RESULTS = 25


class MatchModel(BaseModel):
    repository: str
    path: str
    line_number: int
    start_line: int
    end_line: int
    text: str


class OutputModel(BaseModel):
    source_owner: str
    source_repo: str
    source_pr_number: int
    repo: str = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    path: str
    pattern: str
    ignore_case: bool
    fixed_strings: bool
    word_regexp: bool
    line_number: bool
    before_context: int
    after_context: int
    context_lines: int
    max_count: int
    total_matches: int
    reached_max_count: bool
    evidence_origin: str
    warnings: list[str]
    matches: list[MatchModel]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Search for pattern matches across a repo in scoped Zoekt context.")
    parser.add_argument("pattern_positional", nargs="?")
    parser.add_argument("path_positional", nargs="?")
    parser.add_argument("--repo")
    parser.add_argument("--path")
    parser.add_argument("-e", "--regexp", dest="regexp")
    parser.add_argument("-i", "--ignore-case", nargs="?", const=True, default=False, type=_parse_bool)
    parser.add_argument("-F", "--fixed-strings", nargs="?", const=True, default=False, type=_parse_bool)
    parser.add_argument("-w", "--word-regexp", nargs="?", const=True, default=False, type=_parse_bool)
    parser.add_argument("-n", "--line-number", nargs="?", const=True, default=False, type=_parse_bool)
    parser.add_argument("-A", "--after-context", type=int, default=0)
    parser.add_argument("-B", "--before-context", type=int, default=0)
    parser.add_argument("-C", "--context", "--context-lines", dest="context_lines", type=int, default=0)
    parser.add_argument("-m", "--max-count", type=int, default=DEFAULT_MAX_COUNT)
    return parser.parse_args(argv)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _parse_bool(value: object) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _resolve_pattern(cli: argparse.Namespace) -> str:
    return _clean(cli.regexp) or _clean(cli.pattern_positional)


def _resolve_path(cli: argparse.Namespace) -> str:
    return _clean(cli.path) or _clean(cli.path_positional)


def _effective_context(cli: argparse.Namespace) -> tuple[int, int, int]:
    context_lines = max(0, int(cli.context_lines))
    if context_lines > MAX_CONTEXT_LINES:
        context_lines = MAX_CONTEXT_LINES
    before_context = max(0, int(cli.before_context))
    after_context = max(0, int(cli.after_context))
    before_context = max(before_context, context_lines)
    after_context = max(after_context, context_lines)
    return before_context, after_context, context_lines


def _build_compiled_pattern(pattern: str, *, fixed_strings: bool, ignore_case: bool, word_regexp: bool) -> re.Pattern[str]:
    expression = re.escape(pattern) if fixed_strings else pattern
    if word_regexp:
        expression = rf"\b(?:{expression})\b"
    flags = re.IGNORECASE if ignore_case else 0
    try:
        return re.compile(expression, flags=flags)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc


def _quote_if_whitespace(value: str) -> str:
    if not any(char.isspace() for char in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_search_query(pattern: str, repo: str, path: str) -> str:
    parts: list[str] = [_quote_if_whitespace(pattern)]
    if repo:
        parts.append(f"r:{repo}")
    if path:
        parts.append(f"f:{path}")
    return " ".join(parts)


def _line_matches(compiled: re.Pattern[str], snippet: str, line_number: int, start_line: int) -> bool:
    lines = snippet.splitlines()
    index = line_number - start_line
    if 0 <= index < len(lines):
        return compiled.search(lines[index]) is not None
    return compiled.search(snippet) is not None


async def main():
    try:
        cli = parse_args()
        source_owner, source_repo, source_pr_number = runtime_context.resolve_pr_identity()
        repo = zoekt_tools.normalize_repo(_clean(cli.repo))
        path = _resolve_path(cli)
        pattern = _resolve_pattern(cli)
        if not pattern:
            raise ValueError("missing required arg: pattern")

        before_context, after_context, context_lines = _effective_context(cli)
        max_count = int(cli.max_count)
        if max_count <= 0:
            raise ValueError("max_count must be > 0")

        warnings: list[str] = []
        if max_count > MAX_MAX_COUNT:
            warnings.append(f"max_count clamped from {max_count} to {MAX_MAX_COUNT}")
            max_count = MAX_MAX_COUNT

        if max_count > MAX_SEARCH_RESULTS:
            warnings.append(
                f"zoekt search backend returns at most {MAX_SEARCH_RESULTS} file results per query; "
                "some matches may be truncated"
            )

        search_query = _build_search_query(pattern=pattern, repo=repo, path=path)
        search_results = await asyncio.to_thread(zoekt_tools.search, search_query, MAX_SEARCH_RESULTS, 0)

        compiled = _build_compiled_pattern(
            pattern,
            fixed_strings=bool(cli.fixed_strings),
            ignore_case=bool(cli.ignore_case),
            word_regexp=bool(cli.word_regexp),
        )

        matches: list[dict[str, object]] = []
        seen_anchors: set[tuple[str, str, int]] = set()
        for result in search_results:
            if not isinstance(result, dict):
                continue
            repository = zoekt_tools.normalize_repo(_clean(result.get("repository")))
            if not repository:
                continue
            file_path = _clean(result.get("filename"))
            if not file_path:
                continue
            raw_matches = result.get("matches")
            if not isinstance(raw_matches, list):
                continue

            for raw_match in raw_matches:
                if not isinstance(raw_match, dict):
                    continue
                line_number = int(raw_match.get("line_number") or 0)
                if line_number <= 0:
                    continue
                dedupe_key = (repository, file_path, line_number)
                if dedupe_key in seen_anchors:
                    continue

                start_line = max(1, line_number - before_context)
                end_line = line_number + after_context
                try:
                    snippet = await asyncio.to_thread(zoekt_tools.fetch_content, repository, file_path, start_line, end_line)
                except Exception as exc:
                    warnings.append(f"unable to fetch context for {repository}/{file_path}:L{line_number} ({exc})")
                    snippet = str(raw_match.get("text", "") or "")
                    if not snippet:
                        continue

                if not _line_matches(compiled, snippet, line_number=line_number, start_line=start_line):
                    continue

                seen_anchors.add(dedupe_key)
                matches.append(
                    {
                        "repository": repository,
                        "path": file_path,
                        "line_number": line_number,
                        "start_line": start_line,
                        "end_line": end_line,
                        "text": snippet,
                    }
                )
                if len(matches) >= max_count:
                    break
            if len(matches) >= max_count:
                break

        output = {
            "source_owner": source_owner,
            "source_repo": source_repo,
            "source_pr_number": source_pr_number,
            "repo": repo,
            "path": path,
            "pattern": pattern,
            "ignore_case": bool(cli.ignore_case),
            "fixed_strings": bool(cli.fixed_strings),
            "word_regexp": bool(cli.word_regexp),
            "line_number": bool(cli.line_number),
            "before_context": before_context,
            "after_context": after_context,
            "context_lines": context_lines,
            "max_count": max_count,
            "total_matches": len(matches),
            "reached_max_count": len(matches) >= max_count,
            "evidence_origin": "zoekt_index",
            "warnings": warnings,
            "matches": matches,
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"cross_repo_grep failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
