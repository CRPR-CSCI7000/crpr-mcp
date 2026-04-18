import argparse
import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="


class RepositoryCandidateModel(BaseModel):
    repository: str
    hit_count: int


class OutputModel(BaseModel):
    repo_prefix: str = Field(..., json_schema_extra={"include_in_summary": False})
    repositories: list[str]
    candidates: list[RepositoryCandidateModel]
    total_hits: int


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover candidate repositories from indexed repository names.")
    parser.add_argument("--repo-prefix")
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


async def main():
    try:
        cli = parse_args()
        repo_prefix = str(cli.repo_prefix or "").strip()

        indexed_repos = await asyncio.to_thread(zoekt_tools.list_repos)
        matched_repos = [repo_name for repo_name in indexed_repos if _repo_matches_prefix(repo_name, repo_prefix)]
        repositories = sorted(set(matched_repos))
        candidates: list[dict[str, Any]] = [{"repository": repository, "hit_count": 1} for repository in repositories]
        total_hits = len(repositories)

        output = {
            "repo_prefix": repo_prefix,
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
