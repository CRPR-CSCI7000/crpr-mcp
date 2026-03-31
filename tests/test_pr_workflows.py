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
            {"filename": "src/retry.py", "status": "modified", "additions": 10, "deletions": 2, "changes": 12},
            {"filename": "tests/test_retry.py", "status": "added", "additions": 5, "deletions": 2, "changes": 7},
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


def test_pr_cross_repo_overlap_candidates_excludes_source_repo_by_default(monkeypatch, capsys) -> None:
    module = _load_script_module("pr_cross_repo_overlap_candidates.py")
    _set_cli_args(module, monkeypatch, {"owner": "acme", "repo": "checkout", "pr_number": 12})

    query_log: list[str] = []
    monkeypatch.setattr(
        module.github_tools,
        "list_pull_request_files",
        lambda: [{"filename": "src/retry.py"}],
    )
    monkeypatch.setattr(
        module.zoekt_tools,
        "list_repos",
        lambda: ["github.com/acme/checkout", "github.com/acme/inventory"],
    )
    monkeypatch.setattr(
        module.zoekt_tools,
        "search",
        lambda query, limit, context_lines: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert payload["inspected_repo_count"] == 1
    assert payload["excluded_source_repos"] == ["github.com/acme/checkout"]
    assert payload["no_confirmed_conflicts"] is True
    assert payload["no_confirmed_conflicts_reason"] == "no_overlap_candidates"
    assert payload["coverage_complete"] is False
    assert payload["coverage_reason"] == "candidate_generation_only_requires_followup_validation"
    assert "endpoint_method_route_validation" in payload["required_followup_angles"]
    assert isinstance(payload["suggested_alignment_checks"], list)
    assert all("r:github.com/acme/inventory" in query for query in query_log)


def test_pr_cross_repo_overlap_candidates_include_source_repo_override(monkeypatch, capsys) -> None:
    module = _load_script_module("pr_cross_repo_overlap_candidates.py")
    _set_cli_args(
        module,
        monkeypatch,
        {"owner": "acme", "repo": "checkout", "pr_number": 12, "include_source_repo": True},
    )

    query_log: list[str] = []
    monkeypatch.setattr(
        module.github_tools,
        "list_pull_request_files",
        lambda: [{"filename": "src/retry.py"}],
    )
    monkeypatch.setattr(
        module.zoekt_tools,
        "list_repos",
        lambda: ["github.com/acme/checkout", "github.com/acme/inventory"],
    )
    monkeypatch.setattr(
        module.zoekt_tools,
        "search",
        lambda query, limit, context_lines: query_log.append(query) or [],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert payload["inspected_repo_count"] == 2
    assert payload["excluded_source_repos"] == []
    assert payload["no_confirmed_conflicts"] is True
    assert payload["no_confirmed_conflicts_reason"] == "no_overlap_candidates"
    assert payload["coverage_complete"] is False
    assert payload["coverage_reason"] == "candidate_generation_only_requires_followup_validation"
    assert "endpoint_method_route_validation" in payload["required_followup_angles"]
    assert isinstance(payload["suggested_alignment_checks"], list)
    assert any("r:github.com/acme/checkout" in query for query in query_log)
    assert any("r:github.com/acme/inventory" in query for query in query_log)


def test_pr_cross_repo_overlap_candidates_filters_generic_terms(monkeypatch, capsys) -> None:
    module = _load_script_module("pr_cross_repo_overlap_candidates.py")
    _set_cli_args(module, monkeypatch, {"owner": "acme", "repo": "checkout", "pr_number": 12})

    monkeypatch.setattr(
        module.github_tools,
        "list_pull_request_files",
        lambda: [
            {"filename": "src/components/SettingsModal.tsx"},
            {"filename": "src/hooks/audio/useBackgroundState.ts"},
        ],
    )
    monkeypatch.setattr(module.zoekt_tools, "list_repos", lambda: ["github.com/acme/inventory"])
    monkeypatch.setattr(module.zoekt_tools, "search", lambda query, limit, context_lines: [])

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    search_terms = [str(term).lower() for term in payload["search_terms"]]
    assert "src" not in search_terms
    assert "components" not in search_terms
    assert "hooks" not in search_terms
    assert "settingsmodal" in search_terms
    assert "usebackgroundstate" in search_terms
    assert payload["no_confirmed_conflicts"] is True
    assert payload["no_confirmed_conflicts_reason"] == "no_overlap_candidates"
    assert payload["coverage_complete"] is False
    assert payload["coverage_reason"] == "candidate_generation_only_requires_followup_validation"
    assert "endpoint_method_route_validation" in payload["required_followup_angles"]


def test_pr_cross_repo_overlap_candidates_confirms_contract_evidence_and_suggests_alignment_checks(
    monkeypatch, capsys
) -> None:
    module = _load_script_module("pr_cross_repo_overlap_candidates.py")
    _set_cli_args(module, monkeypatch, {"owner": "acme", "repo": "checkout", "pr_number": 12})

    monkeypatch.setattr(
        module.github_tools,
        "list_pull_request_files",
        lambda: [{"filename": "api/payment_contract.proto"}],
    )
    monkeypatch.setattr(module.zoekt_tools, "list_repos", lambda: ["github.com/acme/inventory"])
    monkeypatch.setattr(
        module.zoekt_tools,
        "search",
        lambda query, limit, context_lines: [
            {
                "repository": "github.com/acme/inventory",
                "filename": "schemas/payment_contract.proto",
                "matches": [{"line_number": 10, "text": "message PaymentContract { ... }"}],
            }
        ],
    )

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert payload["overlap_candidates"]
    assert payload["confirmed_conflicts"]
    assert payload["coverage_complete"] is False
    assert payload["coverage_reason"] == "candidate_generation_only_requires_followup_validation"
    assert "endpoint_method_route_validation" in payload["required_followup_angles"]
    assert payload["no_confirmed_conflicts"] is False
    assert payload["validation_summary"]["confirmed_conflict_count"] == 1
    assert payload["suggested_alignment_checks"]
    first = payload["suggested_alignment_checks"][0]
    assert first["provider_owner"] == "acme"
    assert first["provider_repo"] == "checkout"
    assert first["provider_pr_number"] == 12
    assert first["provider_ref_side"] == "head"
    assert first["consumer_repo"] == "github.com/acme/inventory"
