from src.execution.models import ExecutionResult
from src.skills.workflows.renderers import format_workflow_result_markdown


def test_cross_repo_grep_renderer_strips_github_domain_in_grep_output() -> None:
    markdown = format_workflow_result_markdown(
        "cross_repo_grep",
        ExecutionResult(
            success=True,
            exit_code=0,
            result_json={
                "repo": "github.com/acme/ui",
                "path": "src/redux/actions",
                "pattern": "addToPantry",
                "total_matches": 1,
                "max_count": 20,
                "reached_max_count": False,
                "evidence_origin": "zoekt_index",
                "line_number": True,
                "matches": [
                    {
                        "repository": "github.com/acme/ui",
                        "path": "src/redux/actions/productActions.js",
                        "line_number": 10,
                        "start_line": 10,
                        "text": "/**\n * @function addToPantry",
                    }
                ],
            },
        ),
    )

    assert "acme/ui/src/redux/actions/productActions.js:10:/**" in markdown
    assert "acme/ui/src/redux/actions/productActions.js-11- * @function addToPantry" in markdown
    assert "github.com/acme/ui/src/redux/actions/productActions.js" not in markdown


def test_symbol_definition_renderer_strips_github_domain_in_top_matches() -> None:
    markdown = format_workflow_result_markdown(
        "symbol_definition",
        ExecutionResult(
            success=True,
            exit_code=0,
            result_json={
                "query": "addToPantry",
                "total_hits": 1,
                "results": [
                    {
                        "repository": "github.com/acme/ui",
                        "filename": "src/redux/actions/productActions.js",
                        "matches": [{"line_number": 10, "text": "export const addToPantry = () => {}"}],
                    }
                ],
            },
        ),
    )

    assert "`acme/ui/src/redux/actions/productActions.js`" in markdown
    assert "`github.com/acme/ui/src/redux/actions/productActions.js`" not in markdown


def test_repo_discovery_renderer_strips_github_domain_for_repos_and_prefix() -> None:
    markdown = format_workflow_result_markdown(
        "repo_discovery",
        ExecutionResult(
            success=True,
            exit_code=0,
            result_json={
                "term": "pantry",
                "repo_prefix": "github.com/acme/pantry",
                "search_query": "pantry",
                "repositories": ["github.com/acme/pantry_pal_api", "github.com/acme/pantry_pal_ui"],
                "candidates": [],
                "total_hits": 2,
            },
        ),
    )

    assert "- Repo prefix filter: `acme/pantry`" in markdown
    assert "1. `acme/pantry_pal_api`" in markdown
    assert "2. `acme/pantry_pal_ui`" in markdown
    assert "github.com/acme/pantry" not in markdown
