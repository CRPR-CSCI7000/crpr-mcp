from unittest.mock import Mock, patch

import pytest

from runtime.github_tools import GitHubRuntime, GitHubRuntimeError


def _response(status_code: int, payload, link: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.headers = {"Link": link} if link else {}
    response.text = str(payload)
    response.json.return_value = payload
    return response


def test_list_pull_request_files_paginates_until_exhausted() -> None:
    runtime = GitHubRuntime(token="token", base_url="https://api.github.com", max_retries=1)
    page_one = _response(
        200,
        [{"filename": f"file-{index}.py"} for index in range(100)],
        link='<https://api.github.com/repos/acme/checkout/pulls/1/files?page=2>; rel="next"',
    )
    page_two = _response(200, [{"filename": f"file-{index}.py"} for index in range(100, 120)])

    with patch("runtime.github_tools.requests.request", side_effect=[page_one, page_two]) as request_mock:
        files = runtime.list_pull_request_files("acme", "checkout", 1)

    assert len(files) == 120
    assert request_mock.call_count == 2
    first_params = request_mock.call_args_list[0].kwargs["params"]
    second_params = request_mock.call_args_list[1].kwargs["params"]
    assert first_params["page"] == 1
    assert second_params["page"] == 2


def test_request_retries_on_transient_error_before_success() -> None:
    runtime = GitHubRuntime(token="token", base_url="https://api.github.com", max_retries=2)
    transient = _response(502, {"message": "bad gateway"})
    success = _response(200, {"number": 7, "title": "ok"})

    with (
        patch("runtime.github_tools.requests.request", side_effect=[transient, success]) as request_mock,
        patch("runtime.github_tools.time.sleep") as sleep_mock,
    ):
        pr = runtime.get_pull_request("acme", "checkout", 7)

    assert pr["number"] == 7
    assert request_mock.call_count == 2
    assert sleep_mock.call_count == 1


def test_request_raises_with_error_body_for_non_retryable_failure() -> None:
    runtime = GitHubRuntime(token="token", base_url="https://api.github.com", max_retries=1)
    not_found = _response(404, {"message": "not found"})
    not_found.text = '{"message":"not found"}'

    with patch("runtime.github_tools.requests.request", return_value=not_found):
        with pytest.raises(GitHubRuntimeError, match="status 404"):
            runtime.get_pull_request("acme", "checkout", 404)


def test_get_file_content_decodes_base64_payload() -> None:
    runtime = GitHubRuntime(token="token", base_url="https://api.github.com", max_retries=1)
    contents_payload = {
        "type": "file",
        "encoding": "base64",
        "content": "aGVsbG8gd29ybGQK",
    }
    contents = _response(200, contents_payload)

    with patch("runtime.github_tools.requests.request", return_value=contents):
        text = runtime.get_file_content("acme", "checkout", "src/main.py", ref="abc123")

    assert text == "hello world\n"


def test_get_file_content_rejects_directory_payload() -> None:
    runtime = GitHubRuntime(token="token", base_url="https://api.github.com", max_retries=1)
    directory_payload = [{"path": "src"}]
    directory_response = _response(200, directory_payload)

    with patch("runtime.github_tools.requests.request", return_value=directory_response):
        with pytest.raises(GitHubRuntimeError, match="directory"):
            runtime.get_file_content("acme", "checkout", "src")
