import asyncio
import importlib.util
import json
from pathlib import Path


def _load_script_module(script_name: str):
    script_path = Path(__file__).resolve().parents[1] / "src" / "skills" / "workflows" / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"{script_name}_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load script module: {script_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_cli_args(module, monkeypatch, payload: dict[str, object]) -> None:
    context_env_map = {
        "owner": "CRPR_CONTEXT_OWNER",
        "repo": "CRPR_CONTEXT_REPO",
        "pr_number": "CRPR_CONTEXT_PR_NUMBER",
    }
    argv: list[str] = []
    for key, value in payload.items():
        env_name = context_env_map.get(key)
        if env_name:
            monkeypatch.setenv(env_name, str(value))
            continue
        argv.append(f"--{key.replace('_', '-')}")
        if isinstance(value, bool):
            argv.append("true" if value else "false")
        else:
            argv.append(str(value))

    original_parse_args = module.parse_args
    monkeypatch.setattr(module, "parse_args", lambda argv_override=None: original_parse_args(argv))


def _parse_result_payload(module, stdout: str) -> dict:
    marker = module.RESULT_MARKER
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError("result marker not found in stdout")


def test_pr_impact_assessment_output_shape(monkeypatch, capsys) -> None:
    module = _load_script_module("pr_impact_assessment.py")
    _set_cli_args(module, monkeypatch, {"owner": "acme", "repo": "checkout", "pr_number": 12})

    monkeypatch.setattr(
        module.github_tools,
        "get_pull_request",
        lambda: {
            "number": 12,
            "title": "Harden retries",
            "state": "open",
            "draft": False,
            "changed_files": 2,
            "additions": 15,
            "deletions": 4,
            "commits": 3,
            "user": {"login": "dev"},
            "base": {"ref": "main"},
            "head": {"ref": "feature/retries"},
        },
    )
    monkeypatch.setattr(
        module.github_tools,
        "list_pull_request_files",
        lambda: [
            {
                "filename": "src/retry.py",
                "status": "modified",
                "additions": 10,
                "deletions": 2,
                "changes": 12,
                "patch": "@@ -10,2 +10,5 @@ def retry_once():\n old_line\n+new_line",
            },
            {
                "filename": "tests/test_retry.py",
                "status": "renamed",
                "previous_filename": "tests/retry_old.py",
                "additions": 5,
                "deletions": 2,
                "changes": 7,
                "patch": "@@ -1,0 +1,3 @@\n+def test_retry():\n+    assert True",
            },
        ],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert payload["owner"] == "acme"
    assert payload["repo"] == "checkout"
    assert payload["pr_number"] == 12
    assert payload["pr"]["title"] == "Harden retries"
    assert payload["summary"]["file_count"] == 2
    assert payload["totals"]["files_changed"] == 2
    assert isinstance(payload["status_counts"], list)
    assert isinstance(payload["directory_counts"], list)
    assert isinstance(payload["extension_summary"], list)
    assert isinstance(payload["largest_files"], list)
    assert isinstance(payload["files"], list)
    assert payload["files"][1]["previous_filename"] == "tests/retry_old.py"
    assert payload["files"][0]["has_patch"] is True
    assert payload["files"][0]["hunk_starts"] == [10]
    assert payload["files"][0]["changed_ranges_new"] == [{"start_line": 10, "end_line": 14}]
    assert payload["files"][1]["hunk_starts"] == [1]
    assert payload["files"][1]["changed_ranges_new"] == [{"start_line": 1, "end_line": 3}]
