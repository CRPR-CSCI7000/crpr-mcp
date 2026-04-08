import argparse
import asyncio
import json
from typing import Any

from pydantic import BaseModel

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="


class OutputModel(BaseModel):
    query: str
    input: dict[str, Any]
    results: list[dict[str, Any]]
    total_hits: int


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Find symbol definitions.")
    parser.add_argument("--term")
    parser.add_argument("--repo")
    parser.add_argument("--lang")
    parser.add_argument("--path")
    parser.add_argument("--exclude-path")
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args(argv)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _quote_if_whitespace(value: str) -> str:
    if not any(char.isspace() for char in value):
        return value
    if value.startswith('"') and value.endswith('"'):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_structured_query(
    term: str,
    repo: str,
    lang: str,
    path: str,
    exclude_path: str,
) -> str:
    parts: list[str] = [_quote_if_whitespace(term)]
    if repo:
        parts.append(f"r:{repo}")
    if lang:
        parts.append(f"lang:{lang}")
    if path:
        parts.append(f"f:{path}")
    if exclude_path:
        parts.append(f"-f:{exclude_path}")
    return " ".join(parts)


async def main():
    try:
        cli = parse_args()
        term = _clean(cli.term)
        repo = zoekt_tools.normalize_repo(_clean(cli.repo))
        lang = _clean(cli.lang)
        path = _clean(cli.path)
        exclude_path = _clean(cli.exclude_path)
        if not term:
            raise ValueError("missing required arg: term")

        limit = int(cli.limit)
        if limit <= 0:
            raise ValueError("limit must be > 0")

        query = _build_structured_query(
            term=term,
            repo=repo,
            lang=lang,
            path=path,
            exclude_path=exclude_path,
        )
        results = await asyncio.to_thread(zoekt_tools.search_symbols, query, limit)

        output = {
            "query": query,
            "input": {
                "term": term,
                "repo": repo,
                "lang": lang,
                "path": path,
                "exclude_path": exclude_path,
                "limit": limit,
            },
            "total_hits": len(results),
            "results": results,
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"symbol_definition failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
