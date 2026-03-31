"""Server-internal context lifecycle client backed by Zoekt internal endpoints."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import requests


class ContextLifecycleError(RuntimeError):
    """Raised when immutable PR context lifecycle cannot complete."""


@dataclass(frozen=True)
class ResolvedContext:
    context_id: str
    owner: str
    repo: str
    pr_number: int
    anchor_created_at: str
    manifest_path: str


class ContextLifecycleManager:
    def __init__(
        self,
        *,
        zoekt_api_url: str,
    ) -> None:
        self.zoekt_api_url = str(zoekt_api_url).rstrip("/")

    async def ensure_pr_context(self, owner: str, repo: str, pr_number: int, wait: bool = True) -> ResolvedContext:
        owner_text = str(owner).strip()
        repo_text = str(repo).strip()
        try:
            pr_number_int = int(pr_number)
        except (TypeError, ValueError) as exc:
            raise ContextLifecycleError("pr_number must be an integer") from exc

        if not owner_text or not repo_text:
            raise ContextLifecycleError("owner and repo are required")
        if pr_number_int <= 0:
            raise ContextLifecycleError("pr_number must be > 0")

        payload = {
            "owner": owner_text,
            "repo": repo_text,
            "pr_number": pr_number_int,
            "wait": bool(wait),
        }

        timeout: float | tuple[float, float] | None
        timeout = None if wait else (5.0, 15.0)

        try:
            response = requests.post(
                f"{self.zoekt_api_url}/internal/context/ensure",
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise ContextLifecycleError(f"failed to call Zoekt ensure endpoint: {exc}") from exc

        body = _decode_json_body(response)

        if int(response.status_code) >= 400:
            message = _extract_error_message(body) or _extract_error_body(response.text)
            if not message:
                message = f"Zoekt ensure failed with status {response.status_code}"
            raise ContextLifecycleError(message)

        if not isinstance(body, dict):
            raise ContextLifecycleError("Zoekt ensure endpoint returned non-object payload")

        context_id = str(body.get("context_id", "")).strip()
        anchor_created_at = str(body.get("anchor_created_at", "")).strip()
        manifest_path = str(body.get("manifest_path", "")).strip()
        status = str(body.get("status", "")).strip().upper()

        if not context_id:
            raise ContextLifecycleError("Zoekt ensure response missing context_id")
        if not anchor_created_at:
            raise ContextLifecycleError("Zoekt ensure response missing anchor_created_at")
        if status and status != "READY":
            raise ContextLifecycleError(f"context ensure did not reach READY state (status={status})")

        return ResolvedContext(
            context_id=context_id,
            owner=owner_text,
            repo=repo_text,
            pr_number=pr_number_int,
            anchor_created_at=anchor_created_at,
            manifest_path=manifest_path,
        )

    @staticmethod
    def build_context_id(owner: str, repo: str, pr_number: int, anchor_created_at: str) -> str:
        identity_key = f"{owner.lower()}/{repo.lower()}/{int(pr_number)}@{anchor_created_at}"
        digest = hashlib.sha1(identity_key.encode("utf-8")).hexdigest()[:20]
        return f"ctx_{digest}"

    @staticmethod
    def from_environment(
        *,
        zoekt_api_url: str,
    ) -> ContextLifecycleManager:
        return ContextLifecycleManager(zoekt_api_url=zoekt_api_url)


def _decode_json_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _extract_error_message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("error", "message", "reason"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_error_body(text: str, max_chars: int = 240) -> str:
    body = text.strip()
    if not body:
        return ""
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "..."
