import argparse
import asyncio
import json
import re

from runtime import zoekt_tools

RESULT_MARKER = "__RESULT_JSON__="
MAX_CONTEXT_LINES = 10


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Find usage call-sites with Zoekt-native queries.")
    parser.add_argument("--term")
    parser.add_argument("--raw-query")
    parser.add_argument("--repo")
    parser.add_argument("--lang")
    parser.add_argument("--path")
    parser.add_argument("--exclude-path")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--context-lines", type=int, default=5)
    parser.add_argument("--expand-variants", type=_parse_bool, default=False)
    return parser.parse_args(argv)


def _parse_bool(value: object) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _clean(value: object) -> str:
    return str(value or "").strip()


def _build_structured_query(
    term: str,
    repo: str,
    lang: str,
    path: str,
    exclude_path: str,
) -> str:
    parts: list[str] = [_quote_if_whitespace(term)]
    if repo:
        parts.append(f"r:{repo}")
    if lang:
        parts.append(f"lang:{lang}")
    if path:
        parts.append(f"f:{path}")
    if exclude_path:
        parts.append(f"-f:{exclude_path}")
    return " ".join(parts)


def _quote_if_whitespace(value: str) -> str:
    if not any(char.isspace() for char in value):
        return value
    if value.startswith('"') and value.endswith('"'):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _split_identifier(value: str) -> list[str]:
    phase_one = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    parts = re.split(r"[^A-Za-z0-9]+", phase_one)
    return [part for part in parts if part]


def _style_forms(tokens: list[str]) -> dict[str, str]:
    lower_tokens = [token.lower() for token in tokens]
    if not lower_tokens:
        return {}
    return {
        "snake_case": "_".join(lower_tokens),
        "kebab-case": "-".join(lower_tokens),
        "camelCase": lower_tokens[0] + "".join(token.capitalize() for token in lower_tokens[1:]),
        "PascalCase": "".join(token.capitalize() for token in lower_tokens),
    }


def _pluralize_word(word: str) -> str:
    if word.endswith("y") and len(word) > 1 and word[-2] not in {"a", "e", "i", "o", "u"}:
        return f"{word[:-1]}ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return f"{word}es"
    return f"{word}s"


def _singularize_word(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return f"{word[:-3]}y"
    if word.endswith(("ches", "shes", "xes", "zes", "ses")) and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def _build_term_variants(term: str, expand_variants: bool) -> list[tuple[str, str]]:
    normalized = _clean(term)
    variants: list[tuple[str, str]] = []
    seen_terms: set[str] = set()

    def _add(label: str, candidate: str) -> None:
        value = _clean(candidate)
        if not value or value in seen_terms:
            return
        seen_terms.add(value)
        variants.append((label, value))

    _add("exact", normalized)
    if not expand_variants:
        return variants

    tokens = _split_identifier(normalized)
    if not tokens:
        return variants

    base_forms = _style_forms(tokens)
    for label in ("snake_case", "kebab-case", "camelCase", "PascalCase"):
        candidate = base_forms.get(label)
        if candidate:
            _add(label, candidate)

    singular_tokens = [token.lower() for token in tokens]
    singular_tokens[-1] = _singularize_word(singular_tokens[-1])
    if singular_tokens != [token.lower() for token in tokens]:
        singular_forms = _style_forms(singular_tokens)
        _add("singular_snake_case", singular_forms.get("snake_case", ""))
        _add("singular_camelCase", singular_forms.get("camelCase", ""))

    plural_tokens = [token.lower() for token in tokens]
    plural_tokens[-1] = _pluralize_word(plural_tokens[-1])
    if plural_tokens != [token.lower() for token in tokens]:
        plural_forms = _style_forms(plural_tokens)
        _add("plural_snake_case", plural_forms.get("snake_case", ""))
        _add("plural_camelCase", plural_forms.get("camelCase", ""))

    return variants


def _result_dedup_key(entry: object) -> str:
    if not isinstance(entry, dict):
        return str(entry)
    repository = _clean(entry.get("repository"))
    filename = _clean(entry.get("filename"))
    matches = entry.get("matches")
    first_match = matches[0] if isinstance(matches, list) and matches else {}
    line_number = 0
    text = ""
    if isinstance(first_match, dict):
        try:
            line_number = int(first_match.get("line_number", 0) or 0)
        except (TypeError, ValueError):
            line_number = 0
        text = _clean(first_match.get("text"))
    return "\x1f".join([repository, filename, str(line_number), text])


def _dedupe_results(results: list[object]) -> list[dict]:
    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for entry in results:
        if not isinstance(entry, dict):
            continue
        key = _result_dedup_key(entry)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(entry)
    return deduped


async def main():
    try:
        cli = parse_args()
        term = _clean(cli.term)
        raw_query = _clean(cli.raw_query)
        repo = _clean(cli.repo)
        lang = _clean(cli.lang)
        path = _clean(cli.path)
        exclude_path = _clean(cli.exclude_path)
        limit = int(cli.limit)
        context_lines = int(cli.context_lines)
        expand_variants = bool(cli.expand_variants)

        if limit <= 0:
            raise ValueError("limit must be > 0")
        if context_lines < 0 or context_lines > MAX_CONTEXT_LINES:
            raise ValueError(f"context_lines must be between 0 and {MAX_CONTEXT_LINES}")

        if term and raw_query:
            raise ValueError("`term` and `raw_query` are mutually exclusive")
        if not term and not raw_query:
            raise ValueError("one of `term` or `raw_query` is required")

        mode = "raw" if raw_query else "structured"
        if mode == "raw":
            if repo or lang or path or exclude_path or expand_variants:
                raise ValueError(
                    "raw_query mode does not accept repo/lang/path/exclude_path/expand_variants; use structured mode"
                )
            query_plan: list[tuple[str, str]] = [("raw", raw_query)]
        else:
            term_variants = _build_term_variants(term, expand_variants)
            query_plan = []
            seen_queries: set[str] = set()
            for variant_label, variant_term in term_variants:
                query = _build_structured_query(
                    term=variant_term,
                    repo=repo,
                    lang=lang,
                    path=path,
                    exclude_path=exclude_path,
                )
                if query in seen_queries:
                    continue
                seen_queries.add(query)
                query_plan.append((variant_label, query))

        attempted_queries: list[dict[str, object]] = []
        collected_results: list[object] = []
        total_raw_hits = 0
        for variant_label, query in query_plan:
            matches = await asyncio.to_thread(zoekt_tools.search, query, limit, context_lines)
            hit_count = len(matches)
            total_raw_hits += hit_count
            attempted_queries.append(
                {
                    "query": query,
                    "variant_label": variant_label,
                    "hits": hit_count,
                }
            )
            collected_results.extend(matches)

        deduped_results = _dedupe_results(collected_results)

        output = {
            "mode": mode,
            "input": {
                "term": term,
                "raw_query": raw_query,
                "repo": repo,
                "lang": lang,
                "path": path,
                "exclude_path": exclude_path,
                "limit": limit,
                "context_lines": context_lines,
                "expand_variants": expand_variants,
            },
            "attempted_queries": attempted_queries,
            "total_queries": len(attempted_queries),
            "total_raw_hits": total_raw_hits,
            "total_hits": len(deduped_results),
            "context_lines": context_lines,
            "results": deduped_results[:limit],
        }
        print(RESULT_MARKER + json.dumps(output, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"symbol_usage failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
