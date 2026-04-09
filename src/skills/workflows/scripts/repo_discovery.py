import argparse
import asyncio
import json
import re
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="


class RepositoryCandidateModel(BaseModel):
    repository: str
    hit_count: int


class OutputModel(BaseModel):
    term: str = Field(..., json_schema_extra={"include_in_summary": False})
    repo_prefix: str = Field(..., json_schema_extra={"include_in_summary": False})
    search_query: str = Field(..., json_schema_extra={"include_in_summary": False})
    repositories: list[str]
    candidates: list[RepositoryCandidateModel]
    total_hits: int


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover candidate repositories from a Zoekt query.")
    parser.add_argument("--term")
    parser.add_argument("--repo-prefix")
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args(argv)


def _normalize_repo_prefix(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("https://", "").replace("http://", "")
    normalized = normalized.removesuffix(".git").strip("/")
    return normalized


def _repo_basename(repository: str) -> str:
    if "/" not in repository:
        return repository
    return repository.rsplit("/", maxsplit=1)[-1]


def _repo_matches_prefix(repository: str, repo_prefix: str) -> bool:
    prefix = _normalize_repo_prefix(repo_prefix)
    if not prefix:
        return True
    normalized_repo = _normalize_repo_prefix(repository)
    if "/" in prefix:
        return normalized_repo.startswith(prefix)
    return _repo_basename(normalized_repo).startswith(prefix)


def _repo_prefix_to_r_filter(repo_prefix: str) -> str:
    prefix = _normalize_repo_prefix(repo_prefix)
    if not prefix:
        return ""
    escaped = re.escape(prefix)
    if "/" in prefix:
        return f"^{escaped}.*"
    return rf"^github\.com/[^/]+/{escaped}.*"


async def main():
    try:
        cli = parse_args()
        term = str(cli.term or "").strip()
        repo_prefix = str(cli.repo_prefix or "").strip()

        limit = int(cli.limit)
        if limit <= 0:
            raise ValueError("limit must be > 0")

        cleaned_term = re.sub(r"\btype:repo\b", "", term).strip()
        query_parts: list[str] = []
        if cleaned_term:
            query_parts.append(cleaned_term)
        prefix_filter = _repo_prefix_to_r_filter(repo_prefix)
        if prefix_filter:
            query_parts.append(f"r:{prefix_filter}")

        search_query = ""
        total_hits = 0
        candidates: list[dict[str, object]] = []
        repositories: list[str] = []

        if not cleaned_term:
            indexed_repos = await asyncio.to_thread(zoekt_tools.list_repos)
            matched_repos = [repo_name for repo_name in indexed_repos if _repo_matches_prefix(repo_name, repo_prefix)]
            repositories = sorted(set(matched_repos))
            candidates = [{"repository": repository, "hit_count": 1} for repository in repositories]
            total_hits = len(repositories)
        else:
            search_query = f"type:repo {' '.join(query_parts)}"
            results = await asyncio.to_thread(zoekt_tools.search, search_query, limit, 0)

            repository_counter: Counter[str] = Counter()
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                repository = str(entry.get("repository", "")).strip()
                if repository:
                    repository_counter.update([repository])

            candidates = [
                {"repository": repository, "hit_count": count}
                for repository, count in sorted(repository_counter.items(), key=lambda item: (-item[1], item[0]))
            ]
            repositories = [entry["repository"] for entry in candidates]
            total_hits = len(results)

        output = {
            "term": term,
            "repo_prefix": repo_prefix,
            "search_query": search_query,
            "total_hits": total_hits,
            "repositories": repositories,
            "candidates": candidates,
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"repo_discovery failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
