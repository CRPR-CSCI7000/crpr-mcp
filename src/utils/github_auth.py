import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import jwt
import requests

logger = logging.getLogger(__name__)

_TOKEN_SKEW_SECONDS = 60


class GitHubRuntimeError(RuntimeError):
    """Raised when runtime wrappers fail to communicate with GitHub."""


@dataclass(frozen=True)
class _TokenCache:
    token: str
    expires_at_epoch: float


_cache: _TokenCache | None = None


def _normalize_private_key(raw_key: str) -> str:
    key = raw_key.strip()
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    return key


def _load_private_key() -> str | None:
    raw_key = os.getenv("GITHUB_APP_PRIVATE_KEY")
    if raw_key:
        return _normalize_private_key(raw_key)

    key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
    if key_path:
        try:
            return _normalize_private_key(Path(key_path).read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read GitHub App private key file: %s", exc)
            return None

    return None


def _get_env_int(key: str) -> int | None:
    value = os.getenv(key)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for %s: %s", key, value)
        return None


def _parse_github_datetime(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


def _build_app_jwt(app_id: int, private_key: str) -> str | None:
    now = int(time.time())
    payload = {
        "iat": now - _TOKEN_SKEW_SECONDS,
        "exp": now + 9 * 60,
        "iss": str(app_id),
    }
    try:
        token = jwt.encode(payload, private_key, algorithm="RS256")
    except Exception as exc:
        logger.warning("Failed to build GitHub App JWT: %s", exc)
        return None
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def is_github_app_configured() -> bool:
    return bool(
        _get_env_int("GITHUB_APP_ID")
        and _get_env_int("GITHUB_APP_INSTALLATION_ID")
        and _load_private_key()
    )


def build_auth_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crpr-mcp",
    }


def _get_github_app_installation_token(base_url: str, timeout_seconds: int) -> str | None:
    global _cache

    if not is_github_app_configured():
        return None

    if _cache and (_cache.expires_at_epoch - time.time()) > _TOKEN_SKEW_SECONDS:
        return _cache.token

    app_id = _get_env_int("GITHUB_APP_ID")
    installation_id = _get_env_int("GITHUB_APP_INSTALLATION_ID")
    private_key = _load_private_key()
    if not app_id or not installation_id or not private_key:
        return None

    jwt_token = _build_app_jwt(app_id, private_key)
    if not jwt_token:
        return None

    url = f"{base_url.rstrip('/')}/app/installations/{installation_id}/access_tokens"
    headers = build_auth_headers(jwt_token)

    try:
        response = requests.post(url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("Failed to fetch GitHub App installation token: %s", exc)
        return None

    token = data.get("token")
    expires_at = _parse_github_datetime(data.get("expires_at"))
    if isinstance(token, str) and expires_at:
        _cache = _TokenCache(token=token, expires_at_epoch=expires_at)
        return token

    logger.warning("GitHub App token response missing token or expiry.")
    return None


def resolve_github_token(base_url: str, timeout_seconds: int) -> str:
    token = _get_github_app_installation_token(base_url, timeout_seconds)
    if token:
        return token
    if is_github_app_configured():
        logger.warning("GitHub App auth failed; falling back to GITHUB_TOKEN if available.")

    pat = os.getenv("GITHUB_TOKEN")
    if pat:
        return pat

    raise GitHubRuntimeError("GitHub auth is not configured (GitHub App or GITHUB_TOKEN).")
