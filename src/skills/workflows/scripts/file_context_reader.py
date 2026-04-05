import argparse
import asyncio
import json

from pydantic import BaseModel, Field

from runtime import context as runtime_context
from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="


class OutputModel(BaseModel):
    source_owner: str
    source_repo: str
    source_pr_number: int
    repo: str = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    path: str
    start_line: int
    end_line: int
    content: str
    evidence_origin: str
    warnings: list[str]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Read a bounded line range from one non-source repository file via Zoekt."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--start-line", type=int, required=True)
    parser.add_argument("--end-line", type=int, required=True)
    return parser.parse_args(argv)


def _normalize_repo(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return normalized
    normalized = normalized.replace("https://", "").replace("http://", "")
    normalized = normalized.removesuffix(".git").strip("/")
    if normalized.lower().startswith("github.com/"):
        owner_repo = normalized[len("github.com/") :]
    else:
        owner_repo = normalized
    owner_repo = owner_repo.lower()
    if "/" not in owner_repo:
        return owner_repo
    return f"github.com/{owner_repo}"


async def main():
    try:
        cli = parse_args()
        source_owner, source_repo, source_pr_number = runtime_context.resolve_pr_identity()

        repo = _normalize_repo(str(cli.repo))
        path = str(cli.path).strip()
        if not repo:
            raise ValueError("missing required arg: repo")
        if not path:
            raise ValueError("missing required arg: path")
        start_line = int(cli.start_line)
        end_line = int(cli.end_line)
        warnings: list[str] = []
        max_end = start_line + zoekt_tools.MAX_FETCH_WINDOW_LINES - 1
        if end_line > max_end:
            warnings.append(f"line window clamped from {end_line - start_line + 1} to {zoekt_tools.MAX_FETCH_WINDOW_LINES}")
            end_line = max_end

        content = await asyncio.to_thread(zoekt_tools.fetch_content, repo, path, start_line, end_line)

        output = {
            "source_owner": source_owner,
            "source_repo": source_repo,
            "source_pr_number": source_pr_number,
            "repo": repo,
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "content": content,
            "evidence_origin": "zoekt_index",
            "warnings": warnings,
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"file_context_reader failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
