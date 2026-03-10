import os
import time
from typing import Any

import requests

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_PER_PAGE = 100
MAX_PAGES = 50
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GitHubRuntimeError(RuntimeError):
    """Raised when runtime wrappers fail to communicate with GitHub."""


class GitHubRuntime:
    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        configured_token = token or os.getenv("GITHUB_TOKEN")
        if not configured_token:
            raise GitHubRuntimeError("GITHUB_TOKEN is not set")

        configured_base_url = base_url or os.getenv("GITHUB_API_URL", DEFAULT_GITHUB_API_URL)
        self.base_url = configured_base_url.rstrip("/")
        self.token = configured_token
        self.max_retries = max(1, int(max_retries))

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        path = f"/repos/{owner}/{repo}/pulls/{int(pr_number)}"
        response = self._request("GET", path)
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitHubRuntimeError("unexpected response shape for pull request metadata")
        return payload

    def list_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        path = f"/repos/{owner}/{repo}/pulls/{int(pr_number)}/files"
        return self._request_paginated(path)

    def _request_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        page = 1
        results: list[dict[str, Any]] = []

        while page <= MAX_PAGES:
            page_params = dict(params or {})
            page_params["per_page"] = DEFAULT_PER_PAGE
            page_params["page"] = page
            response = self._request("GET", path, params=page_params)
            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubRuntimeError("unexpected paginated response shape")

            page_items = [item for item in payload if isinstance(item, dict)]
            results.extend(page_items)

            link_header = str(response.headers.get("Link", ""))
            has_next = 'rel="next"' in link_header
            if not has_next or len(payload) < DEFAULT_PER_PAGE:
                return results
            page += 1

        raise GitHubRuntimeError(f"pagination exceeded max pages ({MAX_PAGES})")

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        attempts = 0
        while attempts < self.max_retries:
            attempts += 1
            try:
                response = requests.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                if attempts >= self.max_retries:
                    raise GitHubRuntimeError(f"GitHub request failed after {attempts} attempts: {exc}") from exc
                time.sleep(self._retry_delay_seconds(None, attempts))
                continue

            status_code = int(response.status_code)
            if status_code in RETRYABLE_STATUS_CODES and attempts < self.max_retries:
                time.sleep(self._retry_delay_seconds(response, attempts))
                continue

            if status_code >= 400:
                body = _extract_error_body(response.text)
                if body:
                    raise GitHubRuntimeError(f"GitHub API request failed with status {status_code}: {body}")
                raise GitHubRuntimeError(f"GitHub API request failed with status {status_code}")

            return response

        raise GitHubRuntimeError("GitHub request failed without a response")

    @staticmethod
    def _retry_delay_seconds(response: requests.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = str(response.headers.get("Retry-After", "")).strip()
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        return min(2.0, 0.2 * (2 ** max(0, attempt - 1)))


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


def _extract_error_body(text: str, max_chars: int = 240) -> str:
    body = text.strip()
    if not body:
        return ""
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "..."
