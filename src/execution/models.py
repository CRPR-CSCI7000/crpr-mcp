from typing import Any

from pydantic import BaseModel, Field

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


class ExecutionResult(BaseModel):
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    result_json: JsonValue = None
    timing_ms: int = 0
    safety_rejections: list[str] = Field(default_factory=list)


class WorkflowCliRunRequest(BaseModel):
    command: str
    timeout_seconds: int = 30


class CustomWorkflowCodeRunRequest(BaseModel):
    code: str
    timeout_seconds: int = 30


class GitHubRPCRequest(BaseModel):
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class GitHubRPCResponse(BaseModel):
    ok: bool
    result: JsonValue = None
    error: str | None = None
