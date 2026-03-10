import argparse
import asyncio
import json

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="
MAX_CONTEXT_LINES = 2


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Find symbol usage call-sites.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--context-lines", type=int, default=2)
    return parser.parse_args(argv)


async def main():
    try:
        cli = parse_args()
        query = str(cli.query).strip()
        if not query:
            raise ValueError("missing required arg: query")

        limit = int(cli.limit)
        context_lines = int(cli.context_lines)
        if context_lines < 0 or context_lines > MAX_CONTEXT_LINES:
            raise ValueError(f"context_lines must be between 0 and {MAX_CONTEXT_LINES}")
        results = await asyncio.to_thread(zoekt_tools.search, query, limit, context_lines)

        output = {
            "query": query,
            "context_lines": context_lines,
            "total_hits": len(results),
            "results": results,
        }
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"symbol_usage failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
