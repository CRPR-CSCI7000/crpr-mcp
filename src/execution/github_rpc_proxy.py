import os
import time
from base64 import b64decode
from typing import Any, Callable

import requests

from .github_auth import GitHubRuntimeError, build_auth_headers, resolve_github_token

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_PER_PAGE = 100
MAX_PAGES = 50
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GitHubRPCProxy:
    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        configured_base_url = base_url or os.getenv("GITHUB_API_URL", DEFAULT_GITHUB_API_URL)
        self.base_url = configured_base_url.rstrip("/")
        self.max_retries = max(1, int(max_retries))
        self._token_provider: Callable[[], str]
        if token:
            self._token_provider = lambda: token
        else:
            self._token_provider = lambda: resolve_github_token(
                self.base_url, timeout_seconds=REQUEST_TIMEOUT_SECONDS
            )

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        normalized_method = str(method).strip()
        if normalized_method == "get_pull_request":
            return self.get_pull_request(
                owner=_require_string(params, "owner"),
                repo=_require_string(params, "repo"),
                pr_number=_require_int(params, "pr_number"),
            )
        if normalized_method == "list_pull_request_files":
            return self.list_pull_request_files(
                owner=_require_string(params, "owner"),
                repo=_require_string(params, "repo"),
                pr_number=_require_int(params, "pr_number"),
            )
        if normalized_method == "get_file_content":
            ref_value = params.get("ref")
            if ref_value is None:
                ref = None
            else:
                ref = str(ref_value).strip() or None
            return self.get_file_content(
                owner=_require_string(params, "owner"),
                repo=_require_string(params, "repo"),
                path=_require_string(params, "path"),
                ref=ref,
            )
        raise GitHubRuntimeError(f"unsupported github rpc method: {normalized_method}")

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

    def get_file_content(self, owner: str, repo: str, path: str, ref: str | None = None) -> str:
        cleaned_path = str(path).strip().lstrip("/")
        if not cleaned_path:
            raise GitHubRuntimeError("path is required")

        endpoint = f"/repos/{owner}/{repo}/contents/{cleaned_path}"
        params: dict[str, Any] = {}
        if ref and str(ref).strip():
            params["ref"] = str(ref).strip()

        response = self._request("GET", endpoint, params=params or None)
        payload = response.json()
        if isinstance(payload, list):
            raise GitHubRuntimeError("path points to a directory, expected file")
        if not isinstance(payload, dict):
            raise GitHubRuntimeError("unexpected response shape for file content")

        content = payload.get("content")
        encoding = str(payload.get("encoding", "")).strip().lower()
        if isinstance(content, str) and content and encoding == "base64":
            return _decode_base64_content(content)

        git_url = str(payload.get("git_url", "")).strip()
        if git_url:
            blob_payload = self._request_absolute("GET", git_url).json()
            if isinstance(blob_payload, dict):
                blob_content = blob_payload.get("content")
                blob_encoding = str(blob_payload.get("encoding", "")).strip().lower()
                if isinstance(blob_content, str) and blob_content and blob_encoding == "base64":
                    return _decode_base64_content(blob_content)

        raise GitHubRuntimeError("file content unavailable for this path/ref")

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
        return self._request_absolute(method=method, url=url, params=params)

    def _request_absolute(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        headers = build_auth_headers(self._token_provider())

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


def _require_string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if value is None:
        raise GitHubRuntimeError(f"{key} is required")
    text = str(value).strip()
    if not text:
        raise GitHubRuntimeError(f"{key} is required")
    return text


def _require_int(params: dict[str, Any], key: str) -> int:
    value = params.get(key)
    if value is None:
        raise GitHubRuntimeError(f"{key} is required")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubRuntimeError(f"{key} must be an integer") from exc


def _extract_error_body(text: str, max_chars: int = 240) -> str:
    body = text.strip()
    if not body:
        return ""
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "..."


def _decode_base64_content(content: str) -> str:
    compact = "".join(content.splitlines())
    try:
        return b64decode(compact).decode("utf-8")
    except Exception as exc:
        raise GitHubRuntimeError("failed to decode base64 file content") from exc
