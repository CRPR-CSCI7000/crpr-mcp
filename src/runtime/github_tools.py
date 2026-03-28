import os
from typing import Any

import requests

REQUEST_TIMEOUT_SECONDS = 15
_RPC_URL_ENV = "CRPR_GITHUB_RPC_URL"


class GitHubRuntimeError(RuntimeError):
    """Raised when subprocess runtime cannot call parent-owned GitHub RPC."""


class GitHubRuntime:
    def __init__(
        self,
        rpc_url: str | None = None,
    ) -> None:
        self.rpc_url = str(rpc_url or os.getenv(_RPC_URL_ENV, "")).strip()
        if not self.rpc_url:
            raise GitHubRuntimeError(
                "GitHub parent RPC is not configured. "
                f"Set {_RPC_URL_ENV} in the subprocess environment."
            )

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        payload = self._call(
            "get_pull_request",
            {"owner": owner, "repo": repo, "pr_number": int(pr_number)},
        )
        if not isinstance(payload, dict):
            raise GitHubRuntimeError("unexpected response shape for pull request metadata")
        return payload

    def list_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        payload = self._call(
            "list_pull_request_files",
            {"owner": owner, "repo": repo, "pr_number": int(pr_number)},
        )
        if not isinstance(payload, list):
            raise GitHubRuntimeError("unexpected response shape for pull request files")
        return [item for item in payload if isinstance(item, dict)]

    def get_file_content(self, owner: str, repo: str, path: str, ref: str | None = None) -> str:
        payload = self._call(
            "get_file_content",
            {"owner": owner, "repo": repo, "path": path, "ref": ref},
        )
        if not isinstance(payload, str):
            raise GitHubRuntimeError("unexpected response shape for file content")
        return payload

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                self.rpc_url,
                headers=headers,
                json={"method": method, "params": params},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise GitHubRuntimeError(f"GitHub parent RPC request failed: {exc}") from exc

        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if int(response.status_code) >= 400:
            message = _extract_error_from_payload(payload) or _extract_error_body(response.text)
            if not message:
                message = f"GitHub parent RPC failed with status {response.status_code}"
            raise GitHubRuntimeError(message)

        if not isinstance(payload, dict):
            raise GitHubRuntimeError("GitHub parent RPC returned invalid JSON")

        if payload.get("ok") is not True:
            message = _extract_error_from_payload(payload) or "GitHub parent RPC returned an unknown error"
            raise GitHubRuntimeError(message)

        return payload.get("result")


_RUNTIME: GitHubRuntime | None = None


def _get_runtime() -> GitHubRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = GitHubRuntime()
    return _RUNTIME


def get_pull_request(owner: str, repo: str, pr_number: int) -> dict[str, Any]:
    return _get_runtime().get_pull_request(owner=owner, repo=repo, pr_number=pr_number)


def list_pull_request_files(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    return _get_runtime().list_pull_request_files(owner=owner, repo=repo, pr_number=pr_number)


def get_file_content(owner: str, repo: str, path: str, ref: str | None = None) -> str:
    return _get_runtime().get_file_content(owner=owner, repo=repo, path=path, ref=ref)


def _extract_error_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, str):
        return error.strip()
    return ""


def _extract_error_body(text: str, max_chars: int = 240) -> str:
    body = text.strip()
    if not body:
        return ""
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "..."
