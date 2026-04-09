import asyncio
import importlib.util
import json
from pathlib import Path


def _load_cross_repo_grep_module():
    script_path = Path(__file__).resolve().parents[1] / "src" / "skills" / "workflows" / "scripts" / "cross_repo_grep.py"
    spec = importlib.util.spec_from_file_location("cross_repo_grep_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load cross_repo_grep script module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cross_repo_grep = _load_cross_repo_grep_module()


def _set_cli_args(monkeypatch, payload: dict[str, object]) -> None:
    context_env_map = {
        "source_owner": "CRPR_CONTEXT_OWNER",
        "source_repo": "CRPR_CONTEXT_REPO",
        "source_pr_number": "CRPR_CONTEXT_PR_NUMBER",
    }
    argv: list[str] = []
    for key, value in payload.items():
        env_name = context_env_map.get(key)
        if env_name:
            monkeypatch.setenv(env_name, str(value))
            continue
        if key == "pattern":
            argv.append(str(value))
            continue
        if isinstance(value, bool):
            if value:
                argv.append(f"--{key.replace('_', '-')}")
            continue
        argv.append(f"--{key.replace('_', '-')}")
        argv.append(str(value))
    original_parse_args = cross_repo_grep.parse_args
    monkeypatch.setattr(cross_repo_grep, "parse_args", lambda argv_override=None: original_parse_args(argv))


def _parse_result_payload(stdout: str) -> dict:
    marker = cross_repo_grep.RESULT_MARKER
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError("result marker not found in stdout")


def test_cross_repo_grep_matches_across_files_with_context(monkeypatch, capsys) -> None:
    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "acme",
            "source_repo": "checkout",
            "source_pr_number": 18,
            "repo": "github.com/acme/checkout",
            "pattern": "enqueue_invoice_event",
            "fixed_strings": True,
            "context_lines": 1,
        },
    )
    monkeypatch.setattr(
        cross_repo_grep.zoekt_tools,
        "search",
        lambda query, limit, context_lines: [
            {
                "filename": "apps/billing/views.py",
                "repository": "github.com/acme/checkout",
                "matches": [{"line_number": 10, "text": "enqueue_invoice_event(payload)"}],
            },
            {
                "filename": "jobs/worker.py",
                "repository": "github.com/acme/checkout",
                "matches": [{"line_number": 4, "text": "enqueue_invoice_event(payload)"}],
            },
        ],
    )

    def _fetch_content(repo: str, path: str, start: int, end: int) -> str:
        if path == "apps/billing/views.py":
            return "def create_item(payload):\nenqueue_invoice_event(payload)\nreturn True"
        if path == "jobs/worker.py":
            return "def run_job(payload):\nenqueue_invoice_event(payload)\nreturn None"
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(cross_repo_grep.zoekt_tools, "fetch_content", _fetch_content)

    exit_code = asyncio.run(cross_repo_grep.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert payload["repo"] == "github.com/acme/checkout"
    assert payload["path"] == ""
    assert payload["total_matches"] == 2
    assert payload["matches"][0]["path"] == "apps/billing/views.py"
    assert payload["matches"][0]["line_number"] == 10
    assert payload["matches"][1]["path"] == "jobs/worker.py"


def test_cross_repo_grep_normalizes_repo_when_omitted(monkeypatch, capsys) -> None:
    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "Example-Labs",
            "source_repo": "Billing_API_DEMO",
            "source_pr_number": 18,
            "pattern": "send_invoice",
            "path": "routes/",
        },
    )
    call_log: list[tuple[str, int, int]] = []

    def _search(query: str, limit: int, context_lines: int) -> list[dict[str, object]]:
        call_log.append((query, limit, context_lines))
        return []

    monkeypatch.setattr(cross_repo_grep.zoekt_tools, "search", _search)

    exit_code = asyncio.run(cross_repo_grep.main())
    _ = capsys.readouterr()

    assert exit_code == 0
    assert len(call_log) == 1
    query, limit, context_lines = call_log[0]
    assert "r:" not in query
    assert "f:routes/" in query
    assert limit == 25
    assert context_lines == 0


def test_cross_repo_grep_clamps_max_count(monkeypatch, capsys) -> None:
    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "acme",
            "source_repo": "checkout",
            "source_pr_number": 18,
            "pattern": "hit",
            "max_count": 999,
        },
    )
    monkeypatch.setattr(cross_repo_grep.zoekt_tools, "search", lambda query, limit, context_lines: [])

    exit_code = asyncio.run(cross_repo_grep.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert payload["max_count"] == 250
    assert any("clamped" in warning for warning in payload["warnings"])


def test_cross_repo_grep_requires_pattern(monkeypatch, capsys) -> None:
    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "acme",
            "source_repo": "checkout",
            "source_pr_number": 18,
            "path": "apps/billing",
        },
    )

    exit_code = asyncio.run(cross_repo_grep.main())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "cross_repo_grep failed: missing required arg: pattern" in captured.out


def test_cross_repo_grep_accepts_explicit_boolean_false_values(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CRPR_CONTEXT_OWNER", "acme")
    monkeypatch.setenv("CRPR_CONTEXT_REPO", "checkout")
    monkeypatch.setenv("CRPR_CONTEXT_PR_NUMBER", "18")
    original_parse_args = cross_repo_grep.parse_args
    monkeypatch.setattr(
        cross_repo_grep,
        "parse_args",
        lambda argv_override=None: original_parse_args(
            [
                "add_invoice_item",
                "--path",
                "routes/invoice_routes.py",
                "--fixed-strings",
                "false",
                "--line-number",
                "false",
                "--ignore-case",
                "false",
                "--word-regexp",
                "false",
            ]
        ),
    )
    monkeypatch.setattr(
        cross_repo_grep.zoekt_tools,
        "search",
        lambda query, limit, context_lines: [
            {
                "filename": "routes/invoice_routes.py",
                "repository": "github.com/acme/checkout",
                "matches": [{"line_number": 22, "text": "add_invoice_item(payload)"}],
            }
        ],
    )
    monkeypatch.setattr(
        cross_repo_grep.zoekt_tools,
        "fetch_content",
        lambda repo, path, start, end: "add_invoice_item(payload)",
    )

    exit_code = asyncio.run(cross_repo_grep.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert payload["fixed_strings"] is False
    assert payload["line_number"] is False
    assert payload["ignore_case"] is False
    assert payload["word_regexp"] is False
    assert payload["matches"][0]["repository"] == "github.com/acme/checkout"
