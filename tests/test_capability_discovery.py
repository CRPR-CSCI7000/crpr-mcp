import asyncio
from pathlib import Path

from src.capabilities import CapabilityCatalog
from src.config import ServerConfig
from src.server import CrprMCPServer

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _manifest_path() -> Path:
    return PROJECT_ROOT / "src" / "workflows" / "manifest.yaml"


def test_list_capabilities_excludes_runtime_entries() -> None:
    catalog = CapabilityCatalog(_manifest_path())
    hits = catalog.list_capabilities()

    assert hits
    assert all(hit.kind in {"workflow", "execution_pattern"} for hit in hits)
    assert all(not hit.id.startswith("runtime.") for hit in hits)


def test_read_capability_runtime_id_is_unknown() -> None:
    catalog = CapabilityCatalog(_manifest_path())
    assert catalog.read("runtime.search") is None
    assert catalog.read("runtime.github_get_pull_request") is None


def test_read_capability_custom_workflow_includes_runtime_helpers(monkeypatch) -> None:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    server = CrprMCPServer(ServerConfig())

    markdown = asyncio.run(server.read_capability("execution.run_custom_workflow_code"))

    assert "### Runtime Helpers" in markdown
    assert "runtime.github_tools" in markdown
    assert "runtime.github_get_pull_request" in markdown
    assert "runtime.github_tools.get_pull_request(owner: str, repo: str, pr_number: int) -> Any" in markdown
    assert "runtime.zoekt_tools.search(query: str" in markdown


def test_read_capability_runtime_doc_returns_unknown(monkeypatch) -> None:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    server = CrprMCPServer(ServerConfig())

    markdown = asyncio.run(server.read_capability("runtime.search"))

    assert "unknown capability_id: runtime.search" in markdown


def test_list_capabilities_emphasizes_read_capability(monkeypatch) -> None:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    server = CrprMCPServer(ServerConfig())

    markdown = asyncio.run(server.list_capabilities())

    assert "### Discovery Policy" in markdown
    assert markdown.count("read_capability") >= 6
    assert "Required args:" not in markdown
    assert "Example:" not in markdown


def test_list_capabilities_runtime_helpers_view(monkeypatch) -> None:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    server = CrprMCPServer(ServerConfig())

    markdown = asyncio.run(server.list_capabilities(view="runtime_helpers"))

    assert "## Runtime Helper List" in markdown
    assert "runtime.github_get_pull_request" in markdown
    assert "runtime.search" in markdown
    assert "execution.run_workflow_cli" not in markdown
    assert "read_capability(capability_id=\"execution.run_custom_workflow_code\")" in markdown
