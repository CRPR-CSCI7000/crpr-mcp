import argparse
import asyncio
import json

from pydantic import BaseModel, Field

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="
MAX_LINE_WINDOW = 60


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


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Read a bounded line range from one non-source repository file via Zoekt."
    )
    parser.add_argument("--source-owner", required=True)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--source-pr-number", type=int, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--start-line", type=int, required=True)
    parser.add_argument("--end-line", type=int, required=True)
    return parser.parse_args(argv)


def _normalize_repo_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("https://", "").replace("http://", "")
    normalized = normalized.removesuffix(".git")
    return normalized.strip("/")


def _is_source_repo(candidate_repo: str, source_owner: str, source_repo: str) -> bool:
    normalized_candidate = _normalize_repo_name(candidate_repo)
    source_name = _normalize_repo_name(f"{source_owner}/{source_repo}")
    source_variants = {
        source_name,
        f"github.com/{source_name}",
    }
    return normalized_candidate in source_variants


async def main():
    try:
        cli = parse_args()
        source_owner = str(cli.source_owner).strip()
        source_repo = str(cli.source_repo).strip()
        if not source_owner:
            raise ValueError("missing required arg: source_owner")
        if not source_repo:
            raise ValueError("missing required arg: source_repo")
        source_pr_number = int(cli.source_pr_number)
        if source_pr_number <= 0:
            raise ValueError("source_pr_number must be > 0")

        repo = str(cli.repo).strip()
        path = str(cli.path).strip()
        if not repo:
            raise ValueError("missing required arg: repo")
        if not path:
            raise ValueError("missing required arg: path")
        if _is_source_repo(repo, source_owner, source_repo):
            raise ValueError(
                "source repository reads are blocked for Zoekt file_context_reader in PR-scoped mode; "
                "use pr_file_context_reader for source repo content"
            )

        start_line = int(cli.start_line)
        end_line = int(cli.end_line)
        if start_line <= 0 or end_line <= 0:
            raise ValueError("start_line and end_line must be positive integers")
        if end_line < start_line:
            raise ValueError("end_line must be >= start_line")
        requested_window = end_line - start_line + 1
        if requested_window > MAX_LINE_WINDOW:
            raise ValueError(
                f"requested line window {requested_window} exceeds max {MAX_LINE_WINDOW}; narrow range and retry"
            )

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
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"file_context_reader failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
