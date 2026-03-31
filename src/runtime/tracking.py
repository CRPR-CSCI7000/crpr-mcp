from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TRACKING_FILE_ENV = "CRPR_TRACKING_OUTPUT_PATH"
_TRACKING_RUN_ID_ENV = "CRPR_TRACKING_RUN_ID"
_TRACKING_WORKFLOW_ID_ENV = "CRPR_TRACKING_WORKFLOW_ID"


def tracking_enabled() -> bool:
    return bool(_tracking_file_path()) and bool(_tracking_run_id())


def record_runtime_call(
    *,
    system: str,
    operation: str,
    is_query: bool = False,
    metadata: dict[str, Any] | None = None,
) -> None:
    tracking_path = _tracking_file_path()
    run_id = _tracking_run_id()
    if not tracking_path or not run_id:
        return

    event: dict[str, Any] = {
        "event_type": "runtime_call",
        "run_id": run_id,
        "workflow_id": _tracking_workflow_id(),
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "system": str(system).strip(),
        "operation": str(operation).strip(),
        "is_query": bool(is_query),
    }
    if metadata:
        event["metadata"] = metadata

    try:
        tracking_path.parent.mkdir(parents=True, exist_ok=True)
        with tracking_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")
    except Exception:
        # Tracking must never break runtime execution.
        return


def _tracking_file_path() -> Path | None:
    raw_path = str(os.getenv(_TRACKING_FILE_ENV, "")).strip()
    if not raw_path:
        return None
    return Path(raw_path)


def _tracking_run_id() -> str:
    return str(os.getenv(_TRACKING_RUN_ID_ENV, "")).strip()


def _tracking_workflow_id() -> str:
    return str(os.getenv(_TRACKING_WORKFLOW_ID_ENV, "")).strip()

