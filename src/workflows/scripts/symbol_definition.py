import argparse
import asyncio
import json

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Find symbol definitions.")
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
        results = await asyncio.to_thread(zoekt_tools.search_symbols, query, limit)

        output = {
            "query": query,
            "total_hits": len(results),
            "results": results,
        }
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"symbol_definition failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
