import asyncio
import importlib.util
import json
from pathlib import Path


def _load_file_context_reader_module():
    script_path = Path(__file__).resolve().parents[1] / "src" / "skills" / "workflows" / "scripts" / "file_context_reader.py"
    spec = importlib.util.spec_from_file_location("file_context_reader_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load file_context_reader script module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


file_context_reader = _load_file_context_reader_module()


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
        argv.append(f"--{key.replace('_', '-')}")
        argv.append(str(value))
    original_parse_args = file_context_reader.parse_args
    monkeypatch.setattr(file_context_reader, "parse_args", lambda argv_override=None: original_parse_args(argv))


def _parse_result_payload(stdout: str) -> dict:
    marker = file_context_reader.RESULT_MARKER
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError("result marker not found in stdout")


def test_file_context_reader_allows_window_of_60_lines(monkeypatch, capsys) -> None:
    call_log: list[tuple[str, str, int, int]] = []

    def fake_fetch_content(repo: str, path: str, start_line: int, end_line: int) -> str:
        call_log.append((repo, path, start_line, end_line))
        return "line content"

    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "org",
            "source_repo": "checkout",
            "source_pr_number": 7,
            "repo": "github.com/org/repo",
            "path": "src/main.go",
            "start_line": 1,
            "end_line": 60,
        },
    )
    monkeypatch.setattr(file_context_reader.zoekt_tools, "fetch_content", fake_fetch_content)

    exit_code = asyncio.run(file_context_reader.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert call_log == [("github.com/org/repo", "src/main.go", 1, 60)]
    assert payload["warnings"] == []


def test_file_context_reader_clamps_window_above_max(monkeypatch, capsys) -> None:
    call_log: list[tuple[str, str, int, int]] = []

    def fake_fetch_content(repo: str, path: str, start_line: int, end_line: int) -> str:
        call_log.append((repo, path, start_line, end_line))
        return "line content"

    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "org",
            "source_repo": "checkout",
            "source_pr_number": 7,
            "repo": "github.com/org/repo",
            "path": "src/main.go",
            "start_line": 1,
            "end_line": 66,
        },
    )
    monkeypatch.setattr(file_context_reader.zoekt_tools, "fetch_content", fake_fetch_content)

    exit_code = asyncio.run(file_context_reader.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert call_log == [("github.com/org/repo", "src/main.go", 1, 60)]
    assert payload["end_line"] == 60
    assert any("clamped" in warning for warning in payload["warnings"])


def test_file_context_reader_allows_source_repo_reads(monkeypatch, capsys) -> None:
    called = {"fetch_content": False}

    def fake_fetch_content(repo: str, path: str, start_line: int, end_line: int) -> str:
        called["fetch_content"] = True
        return "source line"

    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "org",
            "source_repo": "checkout",
            "source_pr_number": 7,
            "repo": "github.com/org/checkout",
            "path": "src/main.go",
            "start_line": 1,
            "end_line": 20,
        },
    )
    monkeypatch.setattr(file_context_reader.zoekt_tools, "fetch_content", fake_fetch_content)

    exit_code = asyncio.run(file_context_reader.main())
    _ = capsys.readouterr()

    assert exit_code == 0
    assert called["fetch_content"] is True


def test_file_context_reader_normalizes_owner_repo_input(monkeypatch, capsys) -> None:
    call_log: list[tuple[str, str, int, int]] = []

    def fake_fetch_content(repo: str, path: str, start_line: int, end_line: int) -> str:
        call_log.append((repo, path, start_line, end_line))
        return "line content"

    _set_cli_args(
        monkeypatch,
        {
            "source_owner": "CRPR-CSCI7000",
            "source_repo": "pantry_pal_api_TEST",
            "source_pr_number": 7,
            "repo": "CRPR-CSCI7000/pantry_pal_api_TEST",
            "path": "routes/pantry_routes.py",
            "start_line": 1,
            "end_line": 60,
        },
    )
    monkeypatch.setattr(file_context_reader.zoekt_tools, "fetch_content", fake_fetch_content)

    exit_code = asyncio.run(file_context_reader.main())
    _ = capsys.readouterr()

    assert exit_code == 0
    assert call_log == [("github.com/crpr-csci7000/pantry_pal_api_test", "routes/pantry_routes.py", 1, 60)]
