import asyncio
import importlib.util
import json
from pathlib import Path


def _load_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "src" / "skills" / "workflows" / "scripts" / "pr_file_context_reader.py"
    )
    spec = importlib.util.spec_from_file_location("pr_file_context_reader_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load pr_file_context_reader script module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr_file_context_reader = _load_module()


def _set_cli_args(monkeypatch, payload: dict[str, object]) -> None:
    argv: list[str] = []
    for key, value in payload.items():
        argv.append(f"--{key.replace('_', '-')}")
        argv.append(str(value))
    original_parse_args = pr_file_context_reader.parse_args
    monkeypatch.setattr(
        pr_file_context_reader, "parse_args", lambda argv_override=None: original_parse_args(argv)
    )


def _parse_result_payload(stdout: str) -> dict[str, object]:
    marker = pr_file_context_reader.RESULT_MARKER
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError("result marker not found in stdout")


def test_pr_file_context_reader_reads_head_sha_content(monkeypatch, capsys) -> None:
    _set_cli_args(
        monkeypatch,
        {
            "owner": "acme",
            "repo": "checkout",
            "pr_number": 12,
            "path": "src/service.py",
            "start_line": 2,
            "end_line": 3,
            "ref_side": "head",
        },
    )

    monkeypatch.setattr(
        pr_file_context_reader.github_tools,
        "get_pull_request",
        lambda owner, repo, pr_number: {
            "head": {"sha": "headsha123", "ref": "feature/thing"},
            "base": {"sha": "basesha456", "ref": "main"},
        },
    )
    calls: list[tuple[str, str, str, str]] = []

    def fake_get_file_content(owner: str, repo: str, path: str, ref: str | None = None) -> str:
        calls.append((owner, repo, path, str(ref)))
        return "line1\nline2\nline3\nline4"

    monkeypatch.setattr(pr_file_context_reader.github_tools, "get_file_content", fake_get_file_content)

    exit_code = asyncio.run(pr_file_context_reader.main())
    captured = capsys.readouterr()
    payload = _parse_result_payload(captured.out)

    assert exit_code == 0
    assert calls == [("acme", "checkout", "src/service.py", "headsha123")]
    assert payload["content"] == "line2\nline3"
    assert payload["ref_side"] == "head"
    assert payload["ref_name"] == "feature/thing"
    assert payload["ref_sha"] == "headsha123"
    assert payload["evidence_origin"] == "github_pr_head"


def test_pr_file_context_reader_rejects_window_above_60_lines(monkeypatch, capsys) -> None:
    _set_cli_args(
        monkeypatch,
        {
            "owner": "acme",
            "repo": "checkout",
            "pr_number": 12,
            "path": "src/service.py",
            "start_line": 1,
            "end_line": 61,
        },
    )

    called = {"pull": False, "content": False}

    def fake_get_pull_request(owner: str, repo: str, pr_number: int) -> dict[str, object]:
        called["pull"] = True
        return {}

    def fake_get_file_content(owner: str, repo: str, path: str, ref: str | None = None) -> str:
        called["content"] = True
        return ""

    monkeypatch.setattr(pr_file_context_reader.github_tools, "get_pull_request", fake_get_pull_request)
    monkeypatch.setattr(pr_file_context_reader.github_tools, "get_file_content", fake_get_file_content)

    exit_code = asyncio.run(pr_file_context_reader.main())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert called["pull"] is False
    assert called["content"] is False
    assert "narrow range and retry" in captured.out
