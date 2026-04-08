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
    argv: list[str] = []
    for key, value in payload.items():
        argv.append(f"--{key.replace('_', '-')}")
        argv.append(str(value))

    original_parse_args = module.parse_args
    monkeypatch.setattr(module, "parse_args", lambda argv_override=None: original_parse_args(argv))


def _parse_result_payload(module, stdout: str) -> dict:
    marker = module.RESULT_MARKER
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError("result marker not found in stdout")


def test_symbol_definition_structured_builds_query_fragments(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_definition.py")
    _set_cli_args(
        module,
        monkeypatch,
        {
            "term": "ProcessOrder",
            "repo": "github.com/acme/checkout",
            "lang": "go",
            "path": "internal/services",
            "exclude_path": "testdata",
            "limit": 8,
        },
    )

    query_log: list[str] = []
    monkeypatch.setattr(
        module.zoekt_tools,
        "search_symbols",
        lambda query, limit: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert query_log == ["ProcessOrder r:github.com/acme/checkout lang:go f:internal/services -f:testdata"]
    assert payload["query"] == query_log[0]
    assert payload["input"]["term"] == "ProcessOrder"
    assert payload["total_hits"] == 0


def test_symbol_definition_normalizes_repo_input(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_definition.py")
    _set_cli_args(
        module,
        monkeypatch,
        {
            "term": "buildClient",
            "repo": "Example-Labs/Invoice_UI_DEMO",
            "limit": 5,
        },
    )

    query_log: list[str] = []
    monkeypatch.setattr(
        module.zoekt_tools,
        "search_symbols",
        lambda query, limit: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert query_log == ["buildClient r:github.com/example-labs/invoice_ui_demo"]
    assert payload["input"]["repo"] == "github.com/example-labs/invoice_ui_demo"


def test_symbol_definition_requires_term(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_definition.py")
    _set_cli_args(module, monkeypatch, {"limit": 5})

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "symbol_definition failed: missing required arg: term" in captured.out
