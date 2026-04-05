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


def test_manager_normalizes_base_url() -> None:
    manager = ContextLifecycleManager(zoekt_api_url="http://zoekt")
    assert manager.zoekt_api_url == "http://zoekt"


def test_ensure_pr_context_calls_zoekt_internal_ensure(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ContextLifecycleManager(zoekt_api_url="http://zoekt")

    captured: dict[str, object] = {}

    async def _fake_post_ensure(*, payload: dict[str, object], wait: bool):  # noqa: ANN202
        captured["url"] = f"{manager.zoekt_api_url}/internal/context/ensure"
        captured["json"] = dict(payload)
        captured["wait"] = wait
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

    monkeypatch.setattr(manager, "_post_ensure", _fake_post_ensure)

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
    assert captured["wait"] is True


def test_ensure_pr_context_raises_on_non_ready_status(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ContextLifecycleManager(zoekt_api_url="http://zoekt")

    async def _fake_post_ensure(*, payload: dict[str, object], wait: bool):  # noqa: ANN202, ARG001
        return _FakeResponse(
            200,
            {
                "context_id": "ctx_abc",
                "anchor_created_at": "2026-03-30T00:00:00+00:00",
                "manifest_path": "/manifest.json",
                "status": "BUILDING",
            },
        )

    monkeypatch.setattr(manager, "_post_ensure", _fake_post_ensure)

    with pytest.raises(ContextLifecycleError, match="did not reach READY"):
        asyncio.run(manager.ensure_pr_context(owner="acme", repo="checkout", pr_number=12, wait=True))


def test_ensure_pr_context_raises_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ContextLifecycleManager(zoekt_api_url="http://zoekt")

    async def _fake_post_ensure(*, payload: dict[str, object], wait: bool):  # noqa: ANN202, ARG001
        return _FakeResponse(400, {"error": "context build failed"})

    monkeypatch.setattr(manager, "_post_ensure", _fake_post_ensure)

    with pytest.raises(ContextLifecycleError, match="context build failed"):
        asyncio.run(manager.ensure_pr_context(owner="acme", repo="checkout", pr_number=12, wait=True))
