import argparse
import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="


class OutputModel(BaseModel):
    query: str = Field(..., json_schema_extra={"include_in_summary": False})
    search_query: str = Field(..., json_schema_extra={"include_in_summary": False})
    repositories: list[str]
    results: list[dict[str, Any]]
    total_hits: int


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover candidate repositories for an objective.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args(argv)


async def main():
    try:
        cli = parse_args()
        query = str(cli.query).strip()
        if not query:
            raise ValueError("missing required arg: query")

        limit = int(cli.limit)
        repo_query = query if "type:repo" in query else f"{query} type:repo"
        results = await asyncio.to_thread(zoekt_tools.search, repo_query, limit, 0)

        repositories = sorted({entry.get("repository", "") for entry in results if entry.get("repository")})
        output = {
            "query": query,
            "search_query": repo_query,
            "total_hits": len(results),
            "repositories": repositories,
            "results": results,
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"repo_discovery failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
