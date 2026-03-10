import asyncio
import importlib.util
import json
from pathlib import Path


def _load_script_module(script_name: str):
    script_path = Path(__file__).resolve().parents[1] / "src" / "workflows" / "scripts" / script_name
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


def test_symbol_usage_structured_builds_query_fragments(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_usage.py")
    _set_cli_args(
        module,
        monkeypatch,
        {
            "term": "addToPantry",
            "repo": "github.com/acme/ui",
            "lang": "javascript",
            "path": "src/actions",
            "exclude_path": "test",
            "limit": 8,
            "context_lines": 1,
        },
    )

    query_log: list[str] = []
    monkeypatch.setattr(
        module.zoekt_tools,
        "search",
        lambda query, limit, context_lines: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert query_log == ["addToPantry r:github.com/acme/ui lang:javascript f:src/actions -f:test"]
    assert payload["mode"] == "structured"
    assert payload["total_queries"] == 1
    assert payload["attempted_queries"][0]["variant_label"] == "exact"
    assert payload["attempted_queries"][0]["hits"] == 0


def test_symbol_usage_raw_query_bypasses_builder(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_usage.py")
    raw_query = "r:github.com/acme/ui addToPantry lang:javascript -f:test"
    _set_cli_args(
        module,
        monkeypatch,
        {
            "raw_query": raw_query,
            "limit": 8,
            "context_lines": 1,
        },
    )

    query_log: list[str] = []
    monkeypatch.setattr(
        module.zoekt_tools,
        "search",
        lambda query, limit, context_lines: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert query_log == [raw_query]
    assert payload["mode"] == "raw"
    assert payload["input"]["raw_query"] == raw_query
    assert payload["total_queries"] == 1


def test_symbol_usage_requires_term_or_raw_query(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_usage.py")
    _set_cli_args(module, monkeypatch, {"limit": 5})

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "symbol_usage failed: one of `term` or `raw_query` is required" in captured.out


def test_symbol_usage_variant_expansion_is_opt_in(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_usage.py")
    _set_cli_args(module, monkeypatch, {"term": "add_to_pantry"})

    query_log: list[str] = []
    monkeypatch.setattr(
        module.zoekt_tools,
        "search",
        lambda query, limit, context_lines: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert query_log == ["add_to_pantry"]
    assert payload["total_queries"] == 1
    assert payload["attempted_queries"][0]["variant_label"] == "exact"


def test_symbol_usage_variant_expansion_is_deterministic_when_enabled(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_usage.py")
    _set_cli_args(module, monkeypatch, {"term": "add_to_pantry", "expand_variants": True})

    query_log: list[str] = []
    monkeypatch.setattr(
        module.zoekt_tools,
        "search",
        lambda query, limit, context_lines: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    expected_queries = [
        "add_to_pantry",
        "add-to-pantry",
        "addToPantry",
        "AddToPantry",
        "add_to_pantries",
        "addToPantries",
    ]
    expected_labels = [
        "exact",
        "kebab-case",
        "camelCase",
        "PascalCase",
        "plural_snake_case",
        "plural_camelCase",
    ]

    assert exit_code == 0
    assert query_log == expected_queries
    assert payload["total_queries"] == len(expected_queries)
    assert [entry["variant_label"] for entry in payload["attempted_queries"]] == expected_labels


def test_symbol_usage_deduplicates_merged_results_and_reports_trace(monkeypatch, capsys) -> None:
    module = _load_script_module("symbol_usage.py")
    _set_cli_args(module, monkeypatch, {"term": "add_to_pantry", "expand_variants": True, "limit": 10})

    query_log: list[str] = []
    duplicate_hit = {
        "repository": "github.com/acme/ui",
        "filename": "src/actions/productActions.js",
        "matches": [{"line_number": 11, "text": "dispatch(addToPantry(payload));"}],
    }
    unique_hit = {
        "repository": "github.com/acme/ui",
        "filename": "src/components/ManualItemModal.jsx",
        "matches": [{"line_number": 22, "text": "dispatch(addToPantry(formPayload));"}],
    }

    def _fake_search(query: str, limit: int, context_lines: int):
        query_log.append(query)
        if query.startswith("add_to_pantry"):
            return [duplicate_hit]
        if query.startswith("addToPantry"):
            return [
                {
                    "repository": "github.com/acme/ui",
                    "filename": "src/actions/productActions.js",
                    "matches": [{"line_number": 11, "text": "dispatch(addToPantry(payload));"}],
                },
                unique_hit,
            ]
        return []

    monkeypatch.setattr(module.zoekt_tools, "search", _fake_search)

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert payload["mode"] == "structured"
    assert payload["total_queries"] == len(query_log)
    assert payload["total_raw_hits"] == 3
    assert payload["total_hits"] == 2
    assert len(payload["results"]) == 2
    assert sorted(payload.keys()) == [
        "attempted_queries",
        "context_lines",
        "input",
        "mode",
        "results",
        "total_hits",
        "total_queries",
        "total_raw_hits",
    ]
