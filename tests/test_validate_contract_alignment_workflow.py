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
        "provider_owner": "CRPR_CONTEXT_OWNER",
        "provider_repo": "CRPR_CONTEXT_REPO",
        "provider_pr_number": "CRPR_CONTEXT_PR_NUMBER",
    }
    argv: list[str] = []
    for key, value in payload.items():
        env_name = context_env_map.get(key)
        if env_name:
            monkeypatch.setenv(env_name, str(value))
            continue
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


def _default_cli_args() -> dict[str, object]:
    return {
        "provider_owner": "acme",
        "provider_repo": "checkout",
        "provider_pr_number": 12,
        "provider_path": "api/orders.py",
        "provider_start_line": 1,
        "provider_end_line": 60,
        "consumer_repo": "github.com/acme/web",
        "consumer_path": "src/api/orders.ts",
        "consumer_start_line": 1,
        "consumer_end_line": 60,
    }


def test_validate_contract_alignment_detects_aligned_signals(monkeypatch, capsys) -> None:
    module = _load_script_module("validate_contract_alignment.py")
    _set_cli_args(module, monkeypatch, _default_cli_args())

    provider_content = """
router.post('/v1/orders', async function createOrder(orderId, customerId) {
  return {"order_id": orderId, "customer_id": customerId, "status": "ok"};
}
""".strip()
    consumer_content = """
const submitOrder = async function(orderId, customerId) {
  return axios.post('/v1/orders', { "order_id": orderId, "customer_id": customerId, "status": "ok" });
}
""".strip()

    def fake_fetch_content(repo: str, path: str, start_line: int, end_line: int) -> str:
        if repo == "github.com/acme/checkout":
            return provider_content
        return consumer_content

    monkeypatch.setattr(module.zoekt_tools, "fetch_content", fake_fetch_content)

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert payload["coverage_complete"] is True
    assert payload["alignment"]["keys"]["provider_only"] == []
    assert payload["alignment"]["keys"]["consumer_only"] == []
    assert "order_id" in payload["alignment"]["keys"]["shared"]
    assert "POST /v1/orders" in payload["alignment"]["http_signatures"]["shared"]
    assert payload["warnings"] == []
    assert payload["provider"]["evidence_origin"] == "zoekt_index_head"


def test_validate_contract_alignment_detects_provider_only_drift(monkeypatch, capsys) -> None:
    module = _load_script_module("validate_contract_alignment.py")
    _set_cli_args(module, monkeypatch, _default_cli_args())

    provider_content = """
router.post('/v1/orders', async function createOrder(orderId, customerId, orderType) {
  return {"order_id": orderId, "customer_id": customerId, "order_type": orderType, "status": "ok"};
}
""".strip()
    consumer_content = """
const submitOrder = async function(orderId, customerId) {
  return axios.post('/v1/orders', { "order_id": orderId, "customer_id": customerId, "status": "ok" });
}
""".strip()

    def fake_fetch_content(repo: str, path: str, start_line: int, end_line: int) -> str:
        if repo == "github.com/acme/checkout":
            return provider_content
        return consumer_content

    monkeypatch.setattr(module.zoekt_tools, "fetch_content", fake_fetch_content)

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert "order_type" in payload["alignment"]["keys"]["provider_only"]
    assert "ordertype" in payload["alignment"]["params"]["provider_only"]
    assert payload["findings"]


def test_validate_contract_alignment_returns_partial_coverage_with_warnings(monkeypatch, capsys) -> None:
    module = _load_script_module("validate_contract_alignment.py")
    _set_cli_args(module, monkeypatch, _default_cli_args())

    def fake_fetch_content(repo: str, path: str, start_line: int, end_line: int) -> str:
        if repo == "github.com/acme/checkout":
            return "# notes only"
        return "// no contract content"

    monkeypatch.setattr(module.zoekt_tools, "fetch_content", fake_fetch_content)

    exit_code = asyncio.run(module.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(module, captured.out)

    assert exit_code == 0
    assert payload["coverage_complete"] is False
    assert payload["warnings"]
    assert payload["coverage_reason"] in {
        "one_or_more_sides_have_no_extractable_signals",
        "heuristic_extraction_sparse",
    }
