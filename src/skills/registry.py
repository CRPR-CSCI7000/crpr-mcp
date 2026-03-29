from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

import yaml
from pydantic import BaseModel


class SkillRegistryError(ValueError):
    """Raised when skill documents are invalid."""


@dataclass(frozen=True)
class ViewSkill:
    id: str
    header: str
    path: Path


@dataclass(frozen=True)
class CapabilitySkill:
    id: str
    kind: str
    order: int
    script_path: str | None
    arg_schema: dict[str, Any]
    list_card: str
    read_doc: str
    path: Path


@dataclass(frozen=True)
class RuntimeHelperSkill:
    id: str
    order: int
    call: str | None
    arg_schema: dict[str, Any]
    output_shape: dict[str, Any]
    list_card: str
    detail_doc: str
    path: Path


@dataclass(frozen=True)
class ToolSkill:
    id: str
    description: str
    path: Path


class SkillRegistry:
    _DOC_TYPES = {"view", "capability", "runtime_helper", "tool"}
    _BASE_FIELDS = {"id", "doc_type"}
    _REQUIRED_SECTIONS = {
        "view": {"list_capabilities"},
        "capability": {"list_capabilities", "read_capability"},
        "runtime_helper": {"list_capabilities", "read_capability"},
        "tool": set(),
    }

    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root
        self.views: dict[str, ViewSkill] = {}
        self.capabilities: dict[str, CapabilitySkill] = {}
        self.runtime_helpers: dict[str, RuntimeHelperSkill] = {}
        self.tools: dict[str, ToolSkill] = {}
        self._load()

    def render_view_header(self, view_id: str, *, total: int) -> str:
        view = self.views.get(view_id)
        if view is None:
            raise SkillRegistryError(f"unknown view id: {view_id}")
        return view.header.replace("{{ total }}", str(int(total)))

    def tool_description(self, tool_id: str) -> str | None:
        tool = self.tools.get(tool_id)
        if tool is None:
            return None
        return tool.description

    def _load(self) -> None:
        if not self.skills_root.exists():
            raise SkillRegistryError(f"skills directory not found: {self.skills_root}")

        seen_ids: set[str] = set()
        markdown_files = sorted(self.skills_root.rglob("*.md"))
        if not markdown_files:
            raise SkillRegistryError(f"no markdown skill files found under: {self.skills_root}")

        for path in markdown_files:
            metadata, body = _parse_frontmatter(path)

            metadata_id = _metadata_string(metadata, "id", path)
            if metadata_id in seen_ids:
                raise SkillRegistryError(f"duplicate skill id detected: {metadata_id}")
            seen_ids.add(metadata_id)

            doc_type = _metadata_string(metadata, "doc_type", path)
            if doc_type not in self._DOC_TYPES:
                raise SkillRegistryError(f"invalid doc_type `{doc_type}` in: {path}")

            allowed_fields = set(self._BASE_FIELDS)
            kind = metadata.get("kind")
            order = metadata.get("order")
            execution = metadata.get("execution")

            if doc_type == "capability":
                allowed_fields.update({"kind", "order", "execution"})
                if not isinstance(kind, str) or not kind.strip():
                    raise SkillRegistryError(f"missing required `kind` for `capability` in: {path}")
                kind = kind.strip()
                if kind not in {"workflow", "execution_pattern"}:
                    raise SkillRegistryError(
                        f"capability kind must be `workflow` or `execution_pattern` in: {path}"
                    )

                if not isinstance(order, int) or order < 0:
                    raise SkillRegistryError("missing/invalid required `order` for `capability` in: " f"{path}")

                if kind == "workflow":
                    if not isinstance(execution, dict):
                        raise SkillRegistryError(
                            f"missing/invalid required `execution` mapping for workflow capability in: {path}"
                        )
                    _validate_execution_keys(
                        execution,
                        {"script_path", "arg_schema", "output_shape", "expected_output_shape"},
                        path,
                    )
                elif execution is not None:
                    if not isinstance(execution, dict):
                        raise SkillRegistryError(
                            f"`execution` must be a mapping for execution_pattern capability in: {path}"
                        )
                    _validate_execution_keys(
                        execution,
                        {"arg_schema", "output_shape", "expected_output_shape"},
                        path,
                    )

            if doc_type == "runtime_helper":
                allowed_fields.update({"order", "execution", "kind"})
                if kind is not None and str(kind).strip() != "runtime_helper":
                    raise SkillRegistryError(f"runtime_helper kind must be `runtime_helper` in: {path}")
                if not isinstance(order, int) or order < 0:
                    raise SkillRegistryError(
                        f"missing/invalid required `order` for `runtime_helper` in: {path}"
                    )
                if execution is not None and not isinstance(execution, dict):
                    raise SkillRegistryError(
                        f"`execution` must be a mapping for `runtime_helper` in: {path}"
                    )
                if isinstance(execution, dict):
                    _validate_execution_keys(
                        execution,
                        {"arg_schema", "output_shape", "expected_output_shape", "call"},
                        path,
                    )

            unexpected_fields = sorted(set(metadata.keys()) - allowed_fields)
            if unexpected_fields:
                raise SkillRegistryError(
                    f"unexpected frontmatter keys in {path}: {', '.join(unexpected_fields)}"
                )

            if doc_type == "tool":
                description = body.strip("\n")
                if not description.strip():
                    raise SkillRegistryError(f"empty tool description in: {path}")
                description = f"{description}\n"
                self.tools[metadata_id] = ToolSkill(
                    id=metadata_id,
                    description=description,
                    path=path,
                )
                continue

            sections = _parse_sections(body=body, path=path)
            expected_sections = self._REQUIRED_SECTIONS[doc_type]
            missing = sorted(expected_sections - set(sections.keys()))
            if missing:
                raise SkillRegistryError(f"missing required section(s) in {path}: {', '.join(missing)}")

            extra = sorted(set(sections.keys()) - expected_sections)
            if extra:
                raise SkillRegistryError(f"unexpected section(s) in {path}: {', '.join(extra)}")

            if doc_type == "view":
                self.views[metadata_id] = ViewSkill(
                    id=metadata_id,
                    header=sections["list_capabilities"],
                    path=path,
                )
                continue

            if doc_type == "capability":
                script_path = None
                arg_schema: dict[str, Any] = {}
                expected_output_schema: list[dict[str, str]] = []
                if kind == "workflow":
                    script_path = _execution_string(execution, "script_path", path)
                    arg_schema = _execution_mapping(execution, "arg_schema", path)
                    if "{{EXPECTED_OUTPUT_SUMMARY}}" not in sections["read_capability"]:
                        raise SkillRegistryError(
                            f"workflow capability missing `{{EXPECTED_OUTPUT_SUMMARY}}` placeholder in: {path}"
                        )
                    script_file = self.skills_root.parent / script_path
                    expected_output_schema = _workflow_output_schema_from_script(
                        script_path=script_file,
                        capability_path=path,
                    )
                elif isinstance(execution, dict):
                    arg_schema = _execution_mapping_optional(execution, "arg_schema")
                read_doc = _render_capability_read_doc(
                    capability_id=metadata_id,
                    kind=kind,
                    arg_schema=arg_schema,
                    expected_output_schema=expected_output_schema,
                    read_doc=sections["read_capability"],
                )

                self.capabilities[metadata_id] = CapabilitySkill(
                    id=metadata_id,
                    kind=kind,
                    order=order,
                    script_path=script_path,
                    arg_schema=arg_schema,
                    list_card=sections["list_capabilities"],
                    read_doc=read_doc,
                    path=path,
                )
                continue

            detail_doc = _render_runtime_helper_detail_doc(
                helper_id=metadata_id,
                call=_execution_string_optional(execution, "call"),
                arg_schema=_execution_mapping_optional(execution, "arg_schema"),
                detail_doc=sections["read_capability"],
            )
            self.runtime_helpers[metadata_id] = RuntimeHelperSkill(
                id=metadata_id,
                order=order,
                call=_execution_string_optional(execution, "call"),
                arg_schema=_execution_mapping_optional(execution, "arg_schema"),
                output_shape=_runtime_output_shape(execution),
                list_card=sections["list_capabilities"],
                detail_doc=detail_doc,
                path=path,
            )


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not lines or lines[0].strip() != "---":
        raise SkillRegistryError(f"missing frontmatter start delimiter in: {path}")

    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        raise SkillRegistryError(f"missing frontmatter end delimiter in: {path}")

    frontmatter_text = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])

    try:
        metadata = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise SkillRegistryError(f"invalid frontmatter yaml in {path}: {exc}") from exc

    if not isinstance(metadata, dict):
        raise SkillRegistryError(f"frontmatter must be a mapping in: {path}")

    for required in SkillRegistry._BASE_FIELDS:
        if required not in metadata:
            raise SkillRegistryError(f"missing required frontmatter key `{required}` in: {path}")

    return metadata, body


def _metadata_string(metadata: dict[str, Any], key: str, path: Path) -> str:
    value = metadata.get(key)
    if value is None:
        raise SkillRegistryError(f"missing required frontmatter key `{key}` in: {path}")
    text = str(value).strip()
    if not text:
        raise SkillRegistryError(f"frontmatter key `{key}` must be non-empty in: {path}")
    return text


def _validate_execution_keys(execution: dict[str, Any], allowed_keys: set[str], path: Path) -> None:
    unexpected = sorted(key for key in execution.keys() if key not in allowed_keys)
    if unexpected:
        raise SkillRegistryError(f"unexpected execution keys in {path}: {', '.join(unexpected)}")


def _execution_string(execution: dict[str, Any], key: str, path: Path) -> str:
    value = execution.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillRegistryError(f"missing required `execution.{key}` in: {path}")
    return value.strip()


def _execution_mapping(execution: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = execution.get(key)
    if not isinstance(value, dict):
        raise SkillRegistryError(f"missing/invalid required `execution.{key}` mapping in: {path}")
    return {str(item_key): item_value for item_key, item_value in value.items() if isinstance(item_key, str)}


def _execution_mapping_optional(execution: Any, key: str) -> dict[str, Any]:
    if not isinstance(execution, dict):
        return {}
    value = execution.get(key)
    if not isinstance(value, dict):
        return {}
    return {str(item_key): item_value for item_key, item_value in value.items() if isinstance(item_key, str)}


def _execution_string_optional(execution: Any, key: str) -> str | None:
    if not isinstance(execution, dict):
        return None
    value = execution.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _runtime_output_shape(execution: Any) -> dict[str, Any]:
    if not isinstance(execution, dict):
        return {}
    value = execution.get("output_shape")
    if not isinstance(value, dict):
        value = execution.get("expected_output_shape")
    if not isinstance(value, dict):
        return {}
    return {str(item_key): item_value for item_key, item_value in value.items() if isinstance(item_key, str)}


def _render_capability_read_doc(
    capability_id: str,
    kind: str,
    arg_schema: dict[str, Any],
    expected_output_schema: list[dict[str, str]],
    read_doc: str,
) -> str:
    rendered = read_doc
    if "{{ARG_USAGE}}" in rendered:
        rendered = rendered.replace("{{ARG_USAGE}}", f"`{_capability_arg_usage(capability_id, arg_schema)}`")
    if "{{ARG_TABLE}}" in rendered:
        rendered = rendered.replace("{{ARG_TABLE}}", _capability_arg_table(arg_schema, kind=kind))
    if "{{EXPECTED_OUTPUT_SUMMARY}}" in rendered:
        rendered = rendered.replace(
            "{{EXPECTED_OUTPUT_SUMMARY}}",
            _capability_expected_output_summary(expected_output_schema),
        )
    return rendered


def _capability_arg_usage(capability_id: str, arg_schema: dict[str, Any]) -> str:
    parts: list[str] = []
    for arg_name, schema in arg_schema.items():
        if not isinstance(arg_name, str):
            continue
        schema_dict = schema if isinstance(schema, dict) else {}
        flag = f"--{arg_name.replace('_', '-')}"
        value_type = str(schema_dict.get("type", "value")).strip().lower() or "value"
        value_fragment = f"<{value_type}>"
        if schema_dict.get("required"):
            parts.append(f"{flag} {value_fragment}")
        else:
            parts.append(f"[{flag} {value_fragment}]")
    suffix = f" {' '.join(parts)}" if parts else ""
    return f"{capability_id}{suffix}"


def _capability_arg_table(arg_schema: dict[str, Any], *, kind: str) -> str:
    if not arg_schema:
        return "- (none)"

    lines = [
        "| Name | Type | Required | Default | Description |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for arg_name, schema in arg_schema.items():
        if not isinstance(arg_name, str):
            continue
        schema_dict = schema if isinstance(schema, dict) else {}
        arg_type = str(schema_dict.get("type", "any")).strip() or "any"
        required = "Yes" if schema_dict.get("required") else "No"
        default = "N/A"
        if "default" in schema_dict:
            default = f"`{repr(schema_dict.get('default'))}`"
        description = str(schema_dict.get("description", "")).strip() or "N/A"
        display_name = arg_name
        if kind == "workflow":
            display_name = f"--{arg_name.replace('_', '-')}"
        escaped_name = display_name.replace("|", "\\|")
        escaped_type = arg_type.replace("|", "\\|")
        escaped_description = description.replace("|", "\\|")

        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{escaped_name}`",
                    f"`{escaped_type}`",
                    required,
                    default,
                    escaped_description,
                ]
            )
            + " |"
        )

    return "\n".join(lines)


def _capability_expected_output_summary(expected_output_schema: list[dict[str, str]]) -> str:
    if not expected_output_schema:
        return "- (none)"

    role_renderers = {
        "field": lambda type_name: f"Field with type `{type_name}`.",
        "echoed_input": lambda type_name: f"Echoed input identifier (type `{type_name}`).",
        "summary_details": lambda _type_name: "High-level summary details.",
        "file_list_summary": lambda _type_name: "List of file entries touched by the workflow.",
    }

    lines: list[str] = []
    for item in expected_output_schema:
        field_name = item["name"]
        type_name = item["type"]
        role = item.get("role", "field")
        renderer = role_renderers.get(role)
        if renderer is None:
            raise SkillRegistryError(f"unsupported output schema role `{role}`")
        lines.append(f"- `{field_name}`: {renderer(type_name)}")
    return "\n".join(lines)


def _workflow_output_schema_from_script(
    script_path: Path,
    capability_path: Path,
) -> list[dict[str, str]]:
    if not script_path.exists():
        raise SkillRegistryError(
            f"workflow script missing for output summary extraction: {script_path} (from {capability_path})"
        )

    output_model = _workflow_output_model_from_script(script_path=script_path, capability_path=capability_path)
    parsed: list[dict[str, str]] = []
    allowed_roles = {"field", "echoed_input", "summary_details", "file_list_summary"}

    for field_name, field_info in output_model.model_fields.items():
        schema_extra = field_info.json_schema_extra if isinstance(field_info.json_schema_extra, dict) else {}
        if schema_extra.get("include_in_summary") is False:
            continue

        role = str(schema_extra.get("summary_role", "field")).strip() or "field"
        if role not in allowed_roles:
            raise SkillRegistryError(
                f"invalid OutputModel summary_role `{role}` for field `{field_name}` in {script_path}"
            )

        parsed.append(
            {
                "name": field_name,
                "type": _annotation_to_schema_type(field_info.annotation),
                "role": role,
            }
        )

    if not parsed:
        raise SkillRegistryError(
            f"workflow script OutputModel has no summary-visible fields: {script_path} (from {capability_path})"
        )

    return parsed


def _workflow_output_model_from_script(
    script_path: Path,
    capability_path: Path,
) -> type[BaseModel]:
    module_name = f"_crpr_workflow_{abs(hash(str(script_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise SkillRegistryError(
            f"unable to load workflow script module spec for OutputModel extraction: {script_path}"
        )

    module = importlib.util.module_from_spec(spec)
    src_root = script_path.parents[3]
    src_root_text = str(src_root)
    added_sys_path = False
    if src_root_text not in sys.path:
        sys.path.insert(0, src_root_text)
        added_sys_path = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SkillRegistryError(
            f"failed to import workflow script for OutputModel extraction {script_path}: {exc}"
        ) from exc
    finally:
        if added_sys_path:
            try:
                sys.path.remove(src_root_text)
            except ValueError:
                pass

    output_model = getattr(module, "OutputModel", None)
    if not isinstance(output_model, type) or not issubclass(output_model, BaseModel):
        raise SkillRegistryError(
            f"workflow script missing required OutputModel BaseModel class: {script_path} (from {capability_path})"
        )
    return output_model


def _annotation_to_schema_type(annotation: Any) -> str:
    if annotation is None:
        return "null"
    if annotation in {str}:
        return "string"
    if annotation in {int}:
        return "integer"
    if annotation in {float}:
        return "number"
    if annotation in {bool}:
        return "boolean"
    if annotation in {dict, object, Any}:
        return "object"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "object"

    origin = get_origin(annotation)
    if origin in {list}:
        args = get_args(annotation)
        inner = _annotation_to_schema_type(args[0]) if args else "object"
        return f"list[{inner}]"
    if origin in {dict}:
        return "object"
    if origin in {tuple, set, frozenset}:
        return "list[object]"
    if origin in {UnionType, Union}:
        args = get_args(annotation)
        non_none = [item for item in args if item is not type(None)]
        has_none = len(non_none) != len(args)
        if len(non_none) == 1:
            base = _annotation_to_schema_type(non_none[0])
            return f"{base}|null" if has_none else base
        return "object|null" if has_none else "object"

    return "object"


def _render_runtime_helper_detail_doc(
    helper_id: str,
    call: str | None,
    arg_schema: dict[str, Any],
    detail_doc: str,
) -> str:
    rendered = detail_doc
    if "{{RUNTIME_SIGNATURE}}" in rendered:
        rendered = rendered.replace(
            "{{RUNTIME_SIGNATURE}}",
            _runtime_helper_signature(helper_id=helper_id, call=call, arg_schema=arg_schema),
        )
    if "{{RUNTIME_PARAMETERS}}" in rendered:
        rendered = rendered.replace("{{RUNTIME_PARAMETERS}}", _runtime_helper_parameter_lines(arg_schema))
    return rendered


def _runtime_helper_signature(helper_id: str, call: str | None, arg_schema: dict[str, Any]) -> str:
    call_name = call or helper_id
    params: list[str] = []

    for arg_name, raw_schema in arg_schema.items():
        if not isinstance(arg_name, str):
            continue
        schema = raw_schema if isinstance(raw_schema, dict) else {}
        arg_type = _schema_type_to_python(schema.get("type"))
        if schema.get("required"):
            params.append(f"{arg_name}: {arg_type}")
            continue
        if "default" in schema:
            params.append(f"{arg_name}: {arg_type} = {repr(schema.get('default'))}")
            continue
        params.append(f"{arg_name}: {arg_type} | None = None")

    return f"{call_name}({', '.join(params)}) -> Any"


def _runtime_helper_parameter_lines(arg_schema: dict[str, Any]) -> str:
    lines: list[str] = []
    for arg_name, raw_schema in arg_schema.items():
        if not isinstance(arg_name, str):
            continue
        schema = raw_schema if isinstance(raw_schema, dict) else {}
        arg_type = _schema_type_to_python(schema.get("type"))
        required_text = "required" if schema.get("required") else "optional"
        description = str(schema.get("description", "")).strip()
        parts = [f"`{arg_name}` (`{arg_type}`, {required_text})"]
        if "default" in schema:
            parts.append(f"default `{repr(schema.get('default'))}`")
        if description:
            parts.append(description)
        lines.append(f"- {'; '.join(parts)}")
    if not lines:
        return "- (none)"
    return "\n".join(lines)


def _schema_type_to_python(schema_type: Any) -> str:
    mapping = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "object": "dict[str, Any]",
        "array": "list[Any]",
    }
    key = str(schema_type or "").strip().lower()
    return mapping.get(key, "Any")


_SECTION_MARKER = re.compile(r"^---\s*([A-Za-z0-9_.-]+)\s*---$")


def _parse_sections(body: str, path: Path) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        marker_match = _SECTION_MARKER.fullmatch(stripped)
        if marker_match:
            section_name = marker_match.group(1).strip()
            if not section_name:
                raise SkillRegistryError(f"malformed section marker in: {path}")

            if current_name is not None:
                sections[current_name] = _normalize_block_text(current_lines)

            if section_name in sections:
                raise SkillRegistryError(f"duplicate section `{section_name}` in: {path}")

            current_name = section_name
            current_lines = []
            continue

        if current_name is None:
            if stripped:
                raise SkillRegistryError(f"content outside section markers in: {path}")
            continue

        current_lines.append(raw_line)

    if current_name is not None:
        sections[current_name] = _normalize_block_text(current_lines)

    return sections


def _normalize_block_text(lines: list[str]) -> str:
    start = 0
    end = len(lines)

    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1

    return "\n".join(lines[start:end])
