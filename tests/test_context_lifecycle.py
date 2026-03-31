import asyncio

import pytest

from src.internal_context import ContextLifecycleError, ContextLifecycleManager


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "error"

    def json(self) -> object:
        return self._payload


def test_context_id_is_deterministic_for_same_pr_anchor() -> None:
    context_id_a = ContextLifecycleManager.build_context_id(
        owner="acme",
        repo="checkout",
        pr_number=12,
        anchor_created_at="2025-01-01T00:00:00+00:00",
    )
    context_id_b = ContextLifecycleManager.build_context_id(
        owner="acme",
        repo="checkout",
        pr_number=12,
        anchor_created_at="2025-01-01T00:00:00+00:00",
    )
    assert context_id_a == context_id_b


def test_ensure_pr_context_calls_zoekt_internal_ensure(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ContextLifecycleManager(zoekt_api_url="http://zoekt")

    captured: dict[str, object] = {}

    def _fake_post(url: str, json: dict[str, object], timeout: object):  # noqa: A002
        captured["url"] = url
        captured["json"] = dict(json)
        captured["timeout"] = timeout
        return _FakeResponse(
            200,
            {
                "context_id": "ctx_abc",
                "owner": "acme",
                "repo": "checkout",
                "pr_number": 12,
                "anchor_created_at": "2026-03-30T00:00:00+00:00",
                "manifest_path": "/data/index/contexts/ctx_abc/manifest.json",
                "status": "READY",
            },
        )

    monkeypatch.setattr("src.internal_context.lifecycle.requests.post", _fake_post)

    resolved = asyncio.run(manager.ensure_pr_context(owner="acme", repo="checkout", pr_number=12, wait=True))

    assert resolved.context_id == "ctx_abc"
    assert resolved.owner == "acme"
    assert resolved.repo == "checkout"
    assert resolved.pr_number == 12
    assert captured["url"] == "http://zoekt/internal/context/ensure"
    assert captured["json"] == {
        "owner": "acme",
        "repo": "checkout",
        "pr_number": 12,
        "wait": True,
    }
    assert captured["timeout"] is None


def test_ensure_pr_context_raises_on_non_ready_status(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ContextLifecycleManager(zoekt_api_url="http://zoekt")

    def _fake_post(url: str, json: dict[str, object], timeout: object):  # noqa: A002
        return _FakeResponse(
            200,
            {
                "context_id": "ctx_abc",
                "anchor_created_at": "2026-03-30T00:00:00+00:00",
                "manifest_path": "/manifest.json",
                "status": "BUILDING",
            },
        )

    monkeypatch.setattr("src.internal_context.lifecycle.requests.post", _fake_post)

    with pytest.raises(ContextLifecycleError, match="did not reach READY"):
        asyncio.run(manager.ensure_pr_context(owner="acme", repo="checkout", pr_number=12, wait=True))


def test_ensure_pr_context_raises_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ContextLifecycleManager(zoekt_api_url="http://zoekt")

    def _fake_post(url: str, json: dict[str, object], timeout: object):  # noqa: A002
        return _FakeResponse(400, {"error": "context build failed"})

    monkeypatch.setattr("src.internal_context.lifecycle.requests.post", _fake_post)

    with pytest.raises(ContextLifecycleError, match="context build failed"):
        asyncio.run(manager.ensure_pr_context(owner="acme", repo="checkout", pr_number=12, wait=True))
