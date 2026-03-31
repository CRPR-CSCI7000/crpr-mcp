import argparse
import asyncio
import json
from collections.abc import Mapping

from pydantic import BaseModel, Field

from runtime import context as runtime_context
from runtime import github_tools

RESULT_MARKER = "__RESULT_JSON__="
MAX_LINE_WINDOW = 60


class OutputModel(BaseModel):
    owner: str = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    repo: str = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    pr_number: int = Field(..., json_schema_extra={"summary_role": "echoed_input"})
    path: str
    start_line: int
    end_line: int
    content: str
    ref_side: str
    ref_name: str
    ref_sha: str
    evidence_origin: str


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Read a bounded line range from a pull request source file at head/base SHA."
    )
    parser.add_argument("--path", required=True)
    parser.add_argument("--start-line", type=int, required=True)
    parser.add_argument("--end-line", type=int, required=True)
    parser.add_argument("--ref-side", choices=("head", "base"), default="head")
    return parser.parse_args(argv)


def _coerce_required_string(payload: dict[str, object], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing required arg: {key}")
    return value


def _coerce_required_int(payload: dict[str, object], key: str) -> int:
    try:
        value = int(payload.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"missing required arg: {key}") from exc
    if value <= 0:
        raise ValueError(f"{key} must be > 0")
    return value


def _extract_sha(pr_payload: Mapping[str, object], ref_side: str) -> str:
    ref_data = pr_payload.get(ref_side)
    if not isinstance(ref_data, Mapping):
        raise ValueError(f"pull request payload missing `{ref_side}` block")
    sha = str(ref_data.get("sha", "")).strip()
    if not sha:
        raise ValueError(f"pull request payload missing `{ref_side}.sha`")
    return sha


def _extract_ref_name(pr_payload: Mapping[str, object], ref_side: str) -> str:
    ref_data = pr_payload.get(ref_side)
    if not isinstance(ref_data, Mapping):
        return ""
    return str(ref_data.get("ref", "")).strip()


async def main():
    try:
        cli = parse_args()
        owner, repo, pr_number = runtime_context.resolve_pr_identity()
        path = _coerce_required_string({"path": cli.path}, "path")
        ref_side = str(cli.ref_side).strip().lower() or "head"
        if ref_side not in {"head", "base"}:
            raise ValueError("ref_side must be one of: head, base")

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

        pr = await asyncio.to_thread(github_tools.get_pull_request)
        if not isinstance(pr, Mapping):
            raise ValueError("unexpected pull request payload shape")
        ref_sha = _extract_sha(pr, ref_side=ref_side)
        ref_name = _extract_ref_name(pr, ref_side=ref_side)

        full_content = await asyncio.to_thread(github_tools.get_file_content, path, ref_sha)
        all_lines = full_content.splitlines()
        start_index = start_line - 1
        end_index = min(len(all_lines), end_line)
        selected_lines = all_lines[start_index:end_index] if start_index < len(all_lines) else []

        output = {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "content": "\n".join(selected_lines),
            "ref_side": ref_side,
            "ref_name": ref_name,
            "ref_sha": ref_sha,
            "evidence_origin": f"github_pr_{ref_side}",
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"pr_file_context_reader failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
