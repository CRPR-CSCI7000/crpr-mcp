import asyncio
from pathlib import Path

from src.config import ServerConfig
from src.server import CrprMCPServer
from src.skills.registry import SkillRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _skills_root() -> Path:
    return PROJECT_ROOT / "src" / "skills"


def test_list_capabilities_excludes_runtime_entries() -> None:
    registry = SkillRegistry(_skills_root())
    capabilities = list(registry.capabilities.values())

    assert capabilities
    assert all(skill.kind in {"workflow", "execution_pattern"} for skill in capabilities)
    assert all(not skill.id.startswith("runtime.") for skill in capabilities)


def test_read_capability_runtime_id_is_unknown() -> None:
    registry = SkillRegistry(_skills_root())
    assert registry.capabilities.get("runtime.search") is None
    assert registry.capabilities.get("runtime.github_get_pull_request") is None


def test_read_capability_custom_workflow_includes_runtime_helpers(monkeypatch) -> None:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    server = CrprMCPServer(ServerConfig())

    markdown = asyncio.run(server.read_capability("execution.run_custom_workflow_code"))

    assert "### Runtime Helpers" in markdown
    assert "runtime.github_tools" in markdown
    assert "runtime.github_get_pull_request" in markdown
    assert "runtime.github_tools.get_pull_request(" in markdown
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
    assert "Use `file_context_reader` for most source/cross-repo file reads in scoped Zoekt context." in markdown
    assert "pr_file_context_reader" not in markdown


def test_list_capabilities_runtime_helpers_view(monkeypatch) -> None:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    server = CrprMCPServer(ServerConfig())

    markdown = asyncio.run(server.list_capabilities(view="runtime_helpers"))

    assert "## Runtime Helper List" in markdown
    assert "runtime.github_get_pull_request" in markdown
    assert "runtime.search" in markdown
    assert "execution.run_workflow_cli" not in markdown
    assert "read_capability(capability_id=\"execution.run_custom_workflow_code\")" in markdown


def test_read_capability_symbol_usage_zoekt_first_contract(monkeypatch) -> None:
    monkeypatch.setenv("ZOEKT_API_URL", "http://zoekt")
    server = CrprMCPServer(ServerConfig())

    markdown = asyncio.run(server.read_capability("symbol_usage"))

    assert "### Arg Usage" in markdown
    assert "--term <string>" in markdown
    assert "--raw-query <string>" in markdown
    assert "| `--term` | `string` | No | N/A | Usage term for structured mode query composition. |" in markdown
    assert (
        "| `--raw-query` | `string` | No | N/A | "
        "Raw Zoekt query for direct execution (bypasses structured mode). |" in markdown
    )
    assert "Exactly one of `term` or `raw_query` is required." in markdown
    assert (
        "1. `symbol_usage --term addToPantry --repo github.com/acme/ui "
        "--lang javascript --path src/actions --exclude-path test --limit 8 --context-lines 5`" in markdown
    )
    assert "- `attempted_queries`: Field with type `list[object]`." in markdown
