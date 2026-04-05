import os

_OWNER_ENV = "CRPR_CONTEXT_OWNER"
_REPO_ENV = "CRPR_CONTEXT_REPO"
_PR_NUMBER_ENV = "CRPR_CONTEXT_PR_NUMBER"
_CONTEXT_ID_ENV = "CRPR_CONTEXT_ID"


class ContextRuntimeError(RuntimeError):
    """Raised when scoped runtime context is missing or invalid."""


def resolve_pr_identity(
    owner: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
) -> tuple[str, str, int]:
    resolved_owner = str(owner or os.getenv(_OWNER_ENV, "")).strip()
    resolved_repo = str(repo or os.getenv(_REPO_ENV, "")).strip()
    raw_pr_number = pr_number if pr_number is not None else os.getenv(_PR_NUMBER_ENV)

    if not resolved_owner:
        raise ContextRuntimeError(f"missing required PR context owner ({_OWNER_ENV})")
    if not resolved_repo:
        raise ContextRuntimeError(f"missing required PR context repo ({_REPO_ENV})")

    try:
        resolved_pr_number = int(raw_pr_number)
    except (TypeError, ValueError) as exc:
        raise ContextRuntimeError(f"missing required PR context pr_number ({_PR_NUMBER_ENV})") from exc
    if resolved_pr_number <= 0:
        raise ContextRuntimeError("pr_number must be > 0")

    return resolved_owner, resolved_repo, resolved_pr_number


def resolve_repo_identity(owner: str | None = None, repo: str | None = None) -> tuple[str, str]:
    resolved_owner = str(owner or os.getenv(_OWNER_ENV, "")).strip()
    resolved_repo = str(repo or os.getenv(_REPO_ENV, "")).strip()
    if not resolved_owner:
        raise ContextRuntimeError(f"missing required repository owner ({_OWNER_ENV})")
    if not resolved_repo:
        raise ContextRuntimeError(f"missing required repository name ({_REPO_ENV})")
    return resolved_owner, resolved_repo


def get_context_id(required: bool = False) -> str | None:
    context_id = str(os.getenv(_CONTEXT_ID_ENV, "")).strip()
    if context_id:
        return context_id
    if required:
        raise ContextRuntimeError(f"missing required context id ({_CONTEXT_ID_ENV})")
    return None
