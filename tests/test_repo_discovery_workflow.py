import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def _load_repo_discovery_module():
    script_path = Path(__file__).resolve().parents[1] / "src" / "skills" / "workflows" / "scripts" / "repo_discovery.py"
    spec = importlib.util.spec_from_file_location("repo_discovery_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load repo_discovery script module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repo_discovery = _load_repo_discovery_module()


def _set_cli_args(monkeypatch, payload: dict[str, object]) -> None:
    argv: list[str] = []
    for key, value in payload.items():
        argv.append(f"--{key.replace('_', '-')}")
        argv.append(str(value))
    original_parse_args = repo_discovery.parse_args
    monkeypatch.setattr(repo_discovery, "parse_args", lambda argv_override=None: original_parse_args(argv))


def _parse_result_payload(stdout: str) -> dict:
    marker = repo_discovery.RESULT_MARKER
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError("result marker not found in stdout")


def test_repo_discovery_lists_indexed_repos_with_repo_prefix(monkeypatch, capsys) -> None:
    _set_cli_args(
        monkeypatch,
        {
            "repo_prefix": "github.com/acme/billing",
        },
    )
    monkeypatch.setattr(
        repo_discovery.zoekt_tools,
        "list_repos",
        lambda: [
            "github.com/acme/billing-service",
            "github.com/acme/billing-web",
            "github.com/acme/billing-service",
            "github.com/acme/checkout",
        ],
    )

    exit_code = asyncio.run(repo_discovery.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert payload["repo_prefix"] == "github.com/acme/billing"
    assert payload["repositories"] == [
        "github.com/acme/billing-service",
        "github.com/acme/billing-web",
    ]
    assert payload["candidates"] == [
        {"repository": "github.com/acme/billing-service", "hit_count": 1},
        {"repository": "github.com/acme/billing-web", "hit_count": 1},
    ]
    assert payload["total_hits"] == 2


def test_repo_discovery_returns_all_indexed_repos_when_no_prefix(monkeypatch, capsys) -> None:
    _set_cli_args(monkeypatch, {})
    monkeypatch.setattr(
        repo_discovery.zoekt_tools,
        "list_repos",
        lambda: [
            "github.com/acme/zeta",
            "github.com/acme/alpha",
            "github.com/acme/beta",
            "github.com/acme/alpha",
        ],
    )

    exit_code = asyncio.run(repo_discovery.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert payload["repo_prefix"] == ""
    assert payload["repositories"] == [
        "github.com/acme/alpha",
        "github.com/acme/beta",
        "github.com/acme/zeta",
    ]
    assert payload["total_hits"] == 3


def test_repo_discovery_repo_prefix_only_filters_indexed_repos(monkeypatch, capsys) -> None:
    _set_cli_args(monkeypatch, {"repo_prefix": "pantry_pal"})
    monkeypatch.setattr(
        repo_discovery.zoekt_tools,
        "list_repos",
        lambda: [
            "github.com/acme/pantry_pal_api",
            "github.com/acme/pantry-pal-web",
            "github.com/acme/pantry_pal_worker",
        ],
    )

    exit_code = asyncio.run(repo_discovery.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert payload["repositories"] == [
        "github.com/acme/pantry_pal_api",
        "github.com/acme/pantry_pal_worker",
    ]


def test_repo_discovery_rejects_term_flag(monkeypatch, capsys) -> None:
    _set_cli_args(monkeypatch, {"term": "enqueue_invoice_event"})

    with pytest.raises(SystemExit):
        asyncio.run(repo_discovery.main())
    captured = capsys.readouterr()
    assert "unrecognized arguments: --term" in captured.err


def test_repo_discovery_rejects_raw_query_flag(monkeypatch, capsys) -> None:
    _set_cli_args(monkeypatch, {"raw_query": "type:repo f:billing"})

    with pytest.raises(SystemExit):
        asyncio.run(repo_discovery.main())
    captured = capsys.readouterr()
    assert "unrecognized arguments: --raw-query" in captured.err


def test_repo_discovery_rejects_path_flags(monkeypatch, capsys) -> None:
    _set_cli_args(monkeypatch, {"path": "billing"})

    with pytest.raises(SystemExit):
        asyncio.run(repo_discovery.main())
    captured = capsys.readouterr()
    assert "unrecognized arguments: --path" in captured.err
