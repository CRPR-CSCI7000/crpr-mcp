import argparse
import asyncio
import json
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from runtime import context as runtime_context
from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="
MAX_LINE_WINDOW = 60
_GENERIC_PARAM_NAMES = {
    "self",
    "cls",
    "this",
    "req",
    "res",
    "next",
    "ctx",
    "request",
    "response",
    "args",
    "kwargs",
    "payload",
    "data",
}
_METHOD_TOKEN_RE = re.compile(r"(get|post|put|patch|delete|options|head)", re.IGNORECASE)


class OutputModel(BaseModel):
    provider: dict[str, Any]
    consumer: dict[str, Any]
    signals: dict[str, Any]
    alignment: dict[str, Any]
    findings: list[dict[str, Any]]
    warnings: list[str]
    coverage_complete: bool
    coverage_reason: str
    signal_counts: dict[str, Any]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Validate contract alignment between source PR provider and cross-repo consumer.")
    parser.add_argument("--provider-path", required=True)
    parser.add_argument("--provider-start-line", type=int, required=True)
    parser.add_argument("--provider-end-line", type=int, required=True)
    parser.add_argument("--consumer-repo", required=True)
    parser.add_argument("--consumer-path", required=True)
    parser.add_argument("--consumer-start-line", type=int, required=True)
    parser.add_argument("--consumer-end-line", type=int, required=True)
    return parser.parse_args(argv)


def _coerce_required_string(payload: dict[str, object], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing required arg: {key}")
    return value


def _validate_line_range(start_line: int, end_line: int, label: str) -> None:
    if start_line <= 0 or end_line <= 0:
        raise ValueError(f"{label}_start_line and {label}_end_line must be positive integers")
    if end_line < start_line:
        raise ValueError(f"{label}_end_line must be >= {label}_start_line")
    requested_window = end_line - start_line + 1
    if requested_window > MAX_LINE_WINDOW:
        raise ValueError(f"{label} requested line window {requested_window} exceeds max {MAX_LINE_WINDOW}")


def _extract_keys(content: str) -> set[str]:
    keys: set[str] = set()

    quoted_key_re = re.compile(r"[\"']([A-Za-z_][A-Za-z0-9_\-]{1,80})[\"']\s*:")
    for key in quoted_key_re.findall(content):
        keys.add(key.lower())

    accessor_re = re.compile(
        r"\[\s*[\"']([A-Za-z_][A-Za-z0-9_\-]{1,80})[\"']\s*\]|\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_\-]{1,80})[\"']"
    )
    for first, second in accessor_re.findall(content):
        if first:
            keys.add(first.lower())
        if second:
            keys.add(second.lower())

    return keys


def _split_param_candidates(raw: str) -> Iterable[str]:
    for fragment in raw.split(","):
        normalized = fragment.strip()
        if not normalized:
            continue
        normalized = normalized.replace("...", "").lstrip("*").strip()
        normalized = normalized.split("=", maxsplit=1)[0].strip()
        normalized = normalized.split(":", maxsplit=1)[0].strip()
        if normalized:
            yield normalized


def _extract_params(content: str) -> set[str]:
    params: set[str] = set()
    patterns = [
        re.compile(r"\b(?:def|function)\s+[A-Za-z_][A-Za-z0-9_]*\s*\(([^)]{1,240})\)"),
        re.compile(r"\(([^)]{1,240})\)\s*=>"),
        re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(([^)]{1,240})\)\s*\{"),
    ]
    identifier_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,60}$")

    for pattern in patterns:
        for raw_group in pattern.findall(content):
            for candidate in _split_param_candidates(raw_group):
                if not identifier_re.match(candidate):
                    continue
                normalized = candidate.lower()
                if normalized in _GENERIC_PARAM_NAMES:
                    continue
                params.add(normalized)

    return params


def _normalize_http_signature(method: str, path: str) -> str:
    clean_method = method.strip().upper() if method.strip() else "ANY"
    clean_path = path.strip()
    if not clean_path:
        clean_path = "/"
    clean_path = clean_path.split("?", maxsplit=1)[0]
    return f"{clean_method} {clean_path.lower()}"


def _extract_http_signatures(content: str) -> set[str]:
    signatures: set[str] = set()

    express_route_re = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete|options|head)\s*\(\s*[\"']([^\"']+)[\"']")
    for method, path in express_route_re.findall(content):
        signatures.add(_normalize_http_signature(method, path))

    axios_route_re = re.compile(r"\baxios\.(get|post|put|patch|delete|options|head)\s*\(\s*[\"']([^\"']+)[\"']")
    for method, path in axios_route_re.findall(content):
        signatures.add(_normalize_http_signature(method, path))

    fetch_route_re = re.compile(r"\bfetch\(\s*[\"']([^\"']+)[\"']")
    for path in fetch_route_re.findall(content):
        signatures.add(_normalize_http_signature("ANY", path))

    flask_route_re = re.compile(
        r"@[\w\.]+\.route\(\s*[\"']([^\"']+)[\"'](?:\s*,\s*methods\s*=\s*\[([^\]]+)\])?",
        re.IGNORECASE,
    )
    for path, methods_block in flask_route_re.findall(content):
        methods = _METHOD_TOKEN_RE.findall(methods_block or "")
        if methods:
            for method in methods:
                signatures.add(_normalize_http_signature(method, path))
            continue
        signatures.add(_normalize_http_signature("ANY", path))

    method_path_re = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/[^\s\"'`]+)")
    for method, path in method_path_re.findall(content):
        signatures.add(_normalize_http_signature(method, path))

    return signatures


def _extract_signals(content: str) -> dict[str, list[str]]:
    keys = sorted(_extract_keys(content))
    params = sorted(_extract_params(content))
    http_signatures = sorted(_extract_http_signatures(content))
    return {
        "keys": keys,
        "params": params,
        "http_signatures": http_signatures,
    }


def _align_signal_lists(provider_values: list[str], consumer_values: list[str]) -> dict[str, list[str]]:
    provider_set = set(provider_values)
    consumer_set = set(consumer_values)
    return {
        "shared": sorted(provider_set & consumer_set),
        "provider_only": sorted(provider_set - consumer_set),
        "consumer_only": sorted(consumer_set - provider_set),
    }


def _build_findings(alignment: dict[str, dict[str, list[str]]], coverage_complete: bool) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for category in ("keys", "params", "http_signatures"):
        category_alignment = alignment.get(category) or {}
        provider_only = category_alignment.get("provider_only") or []
        consumer_only = category_alignment.get("consumer_only") or []
        shared = category_alignment.get("shared") or []

        if provider_only:
            findings.append(
                {
                    "category": category,
                    "kind": "provider_only_drift",
                    "count": len(provider_only),
                    "items": provider_only[:25],
                    "confidence": "medium" if coverage_complete else "low",
                }
            )
        if consumer_only:
            findings.append(
                {
                    "category": category,
                    "kind": "consumer_only_drift",
                    "count": len(consumer_only),
                    "items": consumer_only[:25],
                    "confidence": "medium" if coverage_complete else "low",
                }
            )
        if shared:
            findings.append(
                {
                    "category": category,
                    "kind": "shared_signals",
                    "count": len(shared),
                    "items": shared[:25],
                    "confidence": "high" if coverage_complete else "medium",
                }
            )

    if findings:
        return findings

    return [
        {
            "category": "overall",
            "kind": "no_overlap_detected",
            "count": 0,
            "items": [],
            "confidence": "medium" if coverage_complete else "low",
        }
    ]


def _signal_count(signals: dict[str, list[str]]) -> int:
    return len(signals["keys"]) + len(signals["params"]) + len(signals["http_signatures"])


async def main():
    try:
        cli = parse_args()
        provider_owner, provider_repo, provider_pr_number = runtime_context.resolve_pr_identity()
        provider_path = _coerce_required_string({"provider_path": cli.provider_path}, "provider_path")
        provider_start_line = int(cli.provider_start_line)
        provider_end_line = int(cli.provider_end_line)

        consumer_repo = _coerce_required_string({"consumer_repo": cli.consumer_repo}, "consumer_repo")
        consumer_path = _coerce_required_string({"consumer_path": cli.consumer_path}, "consumer_path")
        consumer_start_line = int(cli.consumer_start_line)
        consumer_end_line = int(cli.consumer_end_line)

        _validate_line_range(provider_start_line, provider_end_line, "provider")
        _validate_line_range(consumer_start_line, consumer_end_line, "consumer")

        source_repo_name = f"github.com/{provider_owner}/{provider_repo}"
        provider_content = await asyncio.to_thread(
            zoekt_tools.fetch_content,
            source_repo_name,
            provider_path,
            provider_start_line,
            provider_end_line,
        )
        consumer_content = await asyncio.to_thread(
            zoekt_tools.fetch_content,
            consumer_repo,
            consumer_path,
            consumer_start_line,
            consumer_end_line,
        )

        provider_signals = _extract_signals(provider_content)
        consumer_signals = _extract_signals(consumer_content)
        alignment = {
            "keys": _align_signal_lists(provider_signals["keys"], consumer_signals["keys"]),
            "params": _align_signal_lists(provider_signals["params"], consumer_signals["params"]),
            "http_signatures": _align_signal_lists(
                provider_signals["http_signatures"], consumer_signals["http_signatures"]
            ),
        }

        warnings: list[str] = []
        provider_signal_count = _signal_count(provider_signals)
        consumer_signal_count = _signal_count(consumer_signals)
        if provider_signal_count == 0:
            warnings.append("provider extraction produced no signals")
        elif provider_signal_count < 3:
            warnings.append("provider extraction produced sparse signal coverage")
        if consumer_signal_count == 0:
            warnings.append("consumer extraction produced no signals")
        elif consumer_signal_count < 3:
            warnings.append("consumer extraction produced sparse signal coverage")

        coverage_complete = provider_signal_count >= 3 and consumer_signal_count >= 3
        if coverage_complete:
            coverage_reason = "heuristic_signal_extraction_sufficient"
        elif provider_signal_count == 0 or consumer_signal_count == 0:
            coverage_reason = "one_or_more_sides_have_no_extractable_signals"
        else:
            coverage_reason = "heuristic_extraction_sparse"

        findings = _build_findings(alignment=alignment, coverage_complete=coverage_complete)

        output = {
            "provider": {
                "owner": provider_owner,
                "repo": provider_repo,
                "pr_number": provider_pr_number,
                "path": provider_path,
                "start_line": provider_start_line,
                "end_line": provider_end_line,
                "evidence_origin": "zoekt_index_head",
            },
            "consumer": {
                "repo": consumer_repo,
                "path": consumer_path,
                "start_line": consumer_start_line,
                "end_line": consumer_end_line,
                "evidence_origin": "zoekt_index",
            },
            "signals": {
                "provider": provider_signals,
                "consumer": consumer_signals,
            },
            "alignment": alignment,
            "findings": findings,
            "warnings": warnings,
            "coverage_complete": coverage_complete,
            "coverage_reason": coverage_reason,
            "signal_counts": {
                "provider": provider_signal_count,
                "consumer": consumer_signal_count,
            },
        }
        OutputModel.model_validate(output)
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"validate_contract_alignment failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
