import argparse
import asyncio
import json
from collections import Counter, defaultdict

from runtime import github_tools

RESULT_MARKER = "__RESULT_JSON__="


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Summarize change surface for a pull request.")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    return parser.parse_args(argv)


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


def _directory(path: str) -> str:
    if "/" not in path:
        return "(root)"
    return path.rsplit("/", maxsplit=1)[0]


def _extension(path: str) -> str:
    filename = path.rsplit("/", maxsplit=1)[-1]
    if "." not in filename:
        return "(none)"
    return filename.rsplit(".", maxsplit=1)[-1].lower()


async def main():
    try:
        cli = parse_args()
        owner = _coerce_required_string({"owner": cli.owner}, "owner")
        repo = _coerce_required_string({"repo": cli.repo}, "repo")
        pr_number = _coerce_required_int({"pr_number": cli.pr_number}, "pr_number")

        pr = await asyncio.to_thread(github_tools.get_pull_request, owner, repo, pr_number)
        files = await asyncio.to_thread(github_tools.list_pull_request_files, owner, repo, pr_number)

        status_counts: Counter[str] = Counter()
        directory_counts: Counter[str] = Counter()
        extension_totals: dict[str, dict[str, int]] = defaultdict(
            lambda: {"files": 0, "additions": 0, "deletions": 0, "changes": 0}
        )
        compact_files: list[dict[str, object]] = []
        for file_info in files:
            filename = str(file_info.get("filename", "")).strip()
            if not filename:
                continue

            status = str(file_info.get("status", "unknown"))
            additions = int(file_info.get("additions", 0) or 0)
            deletions = int(file_info.get("deletions", 0) or 0)
            changes = int(file_info.get("changes", additions + deletions) or (additions + deletions))
            directory = _directory(filename)
            extension = _extension(filename)

            status_counts.update([status])
            directory_counts.update([directory])
            extension_totals[extension]["files"] += 1
            extension_totals[extension]["additions"] += additions
            extension_totals[extension]["deletions"] += deletions
            extension_totals[extension]["changes"] += changes
            compact_files.append(
                {
                    "filename": filename,
                    "status": status,
                    "additions": additions,
                    "deletions": deletions,
                    "changes": changes,
                }
            )

        compact_files.sort(key=lambda item: int(item.get("changes", 0)), reverse=True)
        extension_summary = [
            {
                "extension": extension,
                "files": totals["files"],
                "additions": totals["additions"],
                "deletions": totals["deletions"],
                "changes": totals["changes"],
            }
            for extension, totals in sorted(
                extension_totals.items(), key=lambda item: item[1]["changes"], reverse=True
            )
        ]

        output = {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "totals": {
                "files_changed": len(compact_files),
                "additions": int(pr.get("additions", 0) or 0),
                "deletions": int(pr.get("deletions", 0) or 0),
                "changed_files": int(pr.get("changed_files", len(compact_files)) or len(compact_files)),
            },
            "status_counts": [{"status": status, "count": count} for status, count in status_counts.most_common()],
            "directory_counts": [
                {"directory": directory, "count": count} for directory, count in directory_counts.most_common()
            ],
            "extension_summary": extension_summary,
            "largest_files": compact_files[:20],
        }
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"pr_change_surface failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
