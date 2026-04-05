import argparse
import asyncio
import json
import re
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from runtime import context as runtime_context
from runtime import github_tools, zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="
_GENERIC_TERM_BLACKLIST = {
    "src",
    "app",
    "apps",
    "component",
    "components",
    "hook",
    "hooks",
    "context",
    "contexts",
    "lib",
    "libs",
    "util",
    "utils",
    "test",
    "tests",
    "doc",
    "docs",
    "package",
    "packages",
    "internal",
    "client",
    "server",
    "web",
    "api",
    "types",
    "type",
    "config",
    "scripts",
    "assets",
    "public",
    "shared",
}
_CONTRACT_SIGNAL_TOKENS = {
    "api",
    "schema",
    "openapi",
    "swagger",
    "graphql",
    "proto",
    "protobuf",
    "grpc",
    "avro",
    "contract",
    "interface",
    "dto",
    "payload",
    "event",
    "message",
    "webhook",
}
_CONTRACT_SIGNAL_EXTENSIONS = (".proto", ".avsc")


class OutputModel(BaseModel):
    owner: str = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    repo: str = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    pr_number: int = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    include_source_repo: bool
    inspected_repo_count: int
    excluded_source_repos: list[str]
    changed_files: list[str]
    search_terms: list[str]
    overlap_candidates: list[dict[str, Any]]
    confirmed_conflicts: list[dict[str, Any]]
    no_confirmed_conflicts: bool
    no_confirmed_conflicts_reason: str
    coverage_complete: bool
    coverage_reason: str
    required_followup_angles: list[str]
    suggested_alignment_checks: list[dict[str, Any]]
    validation_summary: dict[str, Any]
    errors: list[dict[str, Any]]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Find cross-repository lexical overlap candidates for a PR.")
    parser.add_argument("--include-source-repo", type=_parse_bool, default=False)
    parser.add_argument("--max-repos", type=int, default=0)
    parser.add_argument("--per-term-limit", type=int, default=3)
    return parser.parse_args(argv)


def _parse_bool(value: object) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _coerce_required_string(payload: dict, key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing required arg: {key}")
    return value


def _coerce_required_int(payload: dict, key: str) -> int:
    try:
        value = int(payload.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"missing required arg: {key}") from exc
    if value <= 0:
        raise ValueError(f"{key} must be > 0")
    return value


def _normalize_repo_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("https://", "").replace("http://", "")
    normalized = normalized.removesuffix(".git")
    return normalized.strip("/")


def _is_source_repo(candidate_repo: str, owner: str, repo: str) -> bool:
    normalized_candidate = _normalize_repo_name(candidate_repo)
    source_name = _normalize_repo_name(f"{owner}/{repo}")
    source_variants = {
        source_name,
        f"github.com/{source_name}",
    }
    return normalized_candidate in source_variants


def _split_identifier(value: str) -> list[str]:
    # Split snake_case, kebab-case, and camelCase/PascalCase identifiers into searchable tokens.
    phase_one = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    parts = re.split(r"[^A-Za-z0-9]+", phase_one)
    return [part for part in parts if part]


def _is_specific_term(term: str) -> bool:
    normalized = term.strip().lower()
    if len(normalized) < 4:
        return False
    return normalized not in _GENERIC_TERM_BLACKLIST


def _build_search_terms(files: list[dict[str, object]], limit: int = 12) -> list[str]:
    ordered = OrderedDict()
    for file_info in files:
        filename = str(file_info.get("filename", "")).strip()
        if not filename:
            continue

        basename = filename.rsplit("/", maxsplit=1)[-1]
        stem = basename.rsplit(".", maxsplit=1)[0]
        if _is_specific_term(stem):
            ordered[stem] = None

        for token in _split_identifier(stem):
            if _is_specific_term(token):
                ordered[token] = None

        if "/" in filename:
            directory = filename.rsplit("/", maxsplit=1)[0].strip("/")
            segment = directory.rsplit("/", maxsplit=1)[-1]
            if _is_specific_term(segment):
                ordered[segment] = None

        if len(ordered) >= limit:
            break

    # Fallback to basename terms if every candidate was filtered as too generic.
    if not ordered:
        for file_info in files:
            filename = str(file_info.get("filename", "")).strip()
            if not filename:
                continue
            ordered[filename.rsplit("/", maxsplit=1)[-1]] = None
            if len(ordered) >= limit:
                break

    return list(ordered.keys())[:limit]


def _contains_contract_signal(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    if normalized.endswith(_CONTRACT_SIGNAL_EXTENSIONS):
        return True
    return any(token in normalized for token in _CONTRACT_SIGNAL_TOKENS)


def _match_has_contract_signal(sample: Mapping[str, object]) -> bool:
    filename = str(sample.get("filename", "")).strip()
    if _contains_contract_signal(filename):
        return True

    matches = sample.get("matches")
    if not isinstance(matches, list):
        return False

    for match in matches:
        if not isinstance(match, Mapping):
            continue
        if _contains_contract_signal(str(match.get("text", ""))):
            return True
    return False


def _source_pr_has_contract_artifacts(changed_filenames: list[str]) -> bool:
    return any(_contains_contract_signal(path) for path in changed_filenames)


def _build_confirmed_conflicts(overlap_candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    confirmed: list[dict[str, object]] = []
    for candidate in overlap_candidates:
        repo_name = str(candidate.get("repo", "")).strip()
        if not repo_name:
            continue

        term_matches = candidate.get("term_matches")
        if not isinstance(term_matches, list):
            continue

        distinct_terms: set[str] = set()
        contract_evidence_samples: list[dict[str, str]] = []
        for term_match in term_matches:
            if not isinstance(term_match, Mapping):
                continue
            term = str(term_match.get("term", "")).strip()
            if term:
                distinct_terms.add(term)

            samples = term_match.get("samples")
            if not isinstance(samples, list):
                continue
            for sample in samples:
                if not isinstance(sample, Mapping) or not _match_has_contract_signal(sample):
                    continue
                contract_evidence_samples.append(
                    {
                        "term": term,
                        "filename": str(sample.get("filename", "")).strip(),
                    }
                )

        specific_terms = [term for term in sorted(distinct_terms) if len(term) >= 8]
        if contract_evidence_samples and specific_terms:
            confirmed.append(
                {
                    "repo": repo_name,
                    "total_hits": int(candidate.get("total_hits", 0) or 0),
                    "evidence_terms": specific_terms[:8],
                    "contract_evidence_count": len(contract_evidence_samples),
                    "contract_evidence_samples": contract_evidence_samples[:8],
                }
            )

    confirmed.sort(
        key=lambda item: (int(item.get("contract_evidence_count", 0)), int(item.get("total_hits", 0))),
        reverse=True,
    )
    return confirmed


def _find_provider_path_for_term(changed_filenames: list[str], term: str) -> str:
    normalized_term = term.strip().lower()
    for filename in changed_filenames:
        if normalized_term and normalized_term in filename.lower():
            return filename
    return changed_filenames[0] if changed_filenames else ""


def _first_sample_line(sample: Mapping[str, object]) -> int:
    matches = sample.get("matches")
    if not isinstance(matches, list) or not matches:
        return 1
    first_match = matches[0]
    if not isinstance(first_match, Mapping):
        return 1
    try:
        line_number = int(first_match.get("line_number", 1) or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, line_number)


def _build_suggested_alignment_checks(
    changed_filenames: list[str],
    overlap_candidates: list[dict[str, object]],
    limit: int = 12,
) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    seen: set[str] = set()

    for candidate in overlap_candidates[:8]:
        consumer_repo = str(candidate.get("repo", "")).strip()
        if not consumer_repo:
            continue
        term_matches = candidate.get("term_matches")
        if not isinstance(term_matches, list):
            continue
        for term_match in term_matches[:4]:
            if not isinstance(term_match, Mapping):
                continue
            term = str(term_match.get("term", "")).strip()
            provider_path = _find_provider_path_for_term(changed_filenames, term)
            if not provider_path:
                continue
            samples = term_match.get("samples")
            if not isinstance(samples, list):
                continue
            for sample in samples[:2]:
                if not isinstance(sample, Mapping):
                    continue
                consumer_path = str(sample.get("filename", "")).strip()
                if not consumer_path:
                    continue

                anchor_line = _first_sample_line(sample)
                consumer_start_line = max(1, anchor_line - 5)
                consumer_end_line = consumer_start_line + 19
                dedup_key = "|".join(
                    [provider_path, consumer_repo, consumer_path, str(consumer_start_line), str(consumer_end_line)]
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                suggestions.append(
                    {
                        "term": term,
                        "provider_path": provider_path,
                        "provider_start_line": 1,
                        "provider_end_line": 60,
                        "consumer_repo": consumer_repo,
                        "consumer_path": consumer_path,
                        "consumer_start_line": consumer_start_line,
                        "consumer_end_line": consumer_end_line,
                    }
                )
                if len(suggestions) >= limit:
                    return suggestions

    return suggestions


async def main():
    try:
        cli = parse_args()
        owner, repo, pr_number = runtime_context.resolve_pr_identity()
        include_source_repo = bool(cli.include_source_repo)
        max_repos = int(cli.max_repos)
        per_term_limit = max(1, int(cli.per_term_limit))

        files = await asyncio.to_thread(github_tools.list_pull_request_files)
        changed_filenames = [
            str(file_info.get("filename", "")).strip()
            for file_info in files
            if str(file_info.get("filename", "")).strip()
        ]
        search_terms = _build_search_terms(files)

        indexed_repos = await asyncio.to_thread(zoekt_tools.list_repos)
        excluded_source_repos: list[str] = []
        candidate_repos: list[str] = []
        for indexed_repo in indexed_repos:
            if not include_source_repo and _is_source_repo(indexed_repo, owner, repo):
                excluded_source_repos.append(indexed_repo)
                continue
            candidate_repos.append(indexed_repo)

        if max_repos > 0:
            candidate_repos = candidate_repos[:max_repos]

        overlap_candidates: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for indexed_repo in candidate_repos:
            term_matches: list[dict[str, object]] = []
            total_hits = 0
            for term in search_terms:
                query = f"r:{indexed_repo} {term}"
                try:
                    results = await asyncio.to_thread(zoekt_tools.search, query, per_term_limit, 0)
                except Exception as exc:
                    errors.append({"repo": indexed_repo, "term": term, "error": str(exc)})
                    continue
                if not results:
                    continue
                hit_count = len(results)
                total_hits += hit_count
                term_matches.append(
                    {
                        "term": term,
                        "hits": hit_count,
                        "samples": results[:2],
                    }
                )

            if term_matches:
                overlap_candidates.append(
                    {
                        "repo": indexed_repo,
                        "total_hits": total_hits,
                        "term_matches": term_matches,
                    }
                )

        overlap_candidates.sort(key=lambda item: int(item.get("total_hits", 0)), reverse=True)
        source_pr_has_contract_artifacts = _source_pr_has_contract_artifacts(changed_filenames)
        confirmed_conflicts = (
            _build_confirmed_conflicts(overlap_candidates) if source_pr_has_contract_artifacts else []
        )
        no_confirmed_conflicts = len(confirmed_conflicts) == 0
        if not no_confirmed_conflicts:
            no_confirmed_conflicts_reason = ""
        elif not overlap_candidates:
            no_confirmed_conflicts_reason = "no_overlap_candidates"
        elif not source_pr_has_contract_artifacts:
            no_confirmed_conflicts_reason = "source_pr_has_no_contract_artifacts"
        else:
            no_confirmed_conflicts_reason = "candidates_but_no_contract_evidence"

        output = {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "include_source_repo": include_source_repo,
            "inspected_repo_count": len(candidate_repos),
            "excluded_source_repos": excluded_source_repos,
            "changed_files": changed_filenames,
            "search_terms": search_terms,
            "overlap_candidates": overlap_candidates,
            "confirmed_conflicts": confirmed_conflicts,
            "no_confirmed_conflicts": no_confirmed_conflicts,
            "no_confirmed_conflicts_reason": no_confirmed_conflicts_reason,
            "coverage_complete": False,
            "coverage_reason": "candidate_generation_only_requires_followup_validation",
            "required_followup_angles": [
                "source_contract_read",
                "endpoint_method_route_validation",
                "downstream_payload_mapping_validation",
            ],
            "suggested_alignment_checks": _build_suggested_alignment_checks(
                changed_filenames=changed_filenames,
                overlap_candidates=overlap_candidates,
            ),
            "validation_summary": {
                "source_pr_has_contract_artifacts": source_pr_has_contract_artifacts,
                "overlap_candidate_count": len(overlap_candidates),
                "confirmed_conflict_count": len(confirmed_conflicts),
            },
            "errors": errors,
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"pr_cross_repo_overlap_candidates failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
