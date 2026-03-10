import ast

_ALLOWED_IMPORTS = {
    "argparse",
    "asyncio",
    "collections",
    "dataclasses",
    "datetime",
    "difflib",
    "functools",
    "itertools",
    "json",
    "math",
    "re",
    "sys",
    "statistics",
    "string",
    "textwrap",
    "typing",
    "runtime.github_tools",
    "runtime.zoekt_tools",
}

_ALLOWED_RUNTIME_FROM_IMPORTS = {
    "github_tools",
    "zoekt_tools",
}

_BANNED_IMPORT_PREFIXES = {
    "builtins",
    "ctypes",
    "importlib",
    "multiprocessing",
    "os",
    "pathlib",
    "shlex",
    "shutil",
    "socket",
    "subprocess",
    "tempfile",
}

_BANNED_CALLS = {
    "compile",
    "eval",
    "exec",
    "input",
    "open",
    "__import__",
}


class SafetyError(ValueError):
    """Raised when script safety validation cannot run."""


def validate_custom_workflow_code(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax_error: {exc.msg} at line {exc.lineno}"]

    rejections: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
                _check_import(module_name, rejections)

        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "runtime":
                for alias in node.names:
                    if alias.name not in _ALLOWED_RUNTIME_FROM_IMPORTS:
                        rejections.append(f"disallowed_import: runtime.{alias.name}")
                continue
            _check_import(module_name, rejections)

        if isinstance(node, ast.Call):
            call_name = _call_name(node)
            if call_name in _BANNED_CALLS:
                rejections.append(f"banned_call: {call_name}")

    seen: set[str] = set()
    unique_rejections: list[str] = []
    for rejection in rejections:
        if rejection not in seen:
            unique_rejections.append(rejection)
            seen.add(rejection)

    return unique_rejections


def validate_ephemeral_script(code: str) -> list[str]:
    return validate_custom_workflow_code(code)


def get_allowed_runtime_modules() -> list[str]:
    modules = {module for module in _ALLOWED_IMPORTS if module.startswith("runtime.")}
    modules.update(f"runtime.{name}" for name in _ALLOWED_RUNTIME_FROM_IMPORTS)
    return sorted(modules)


def _check_import(module_name: str, rejections: list[str]) -> None:
    if not module_name:
        return

    if any(module_name == banned or module_name.startswith(f"{banned}.") for banned in _BANNED_IMPORT_PREFIXES):
        rejections.append(f"banned_import: {module_name}")
        return

    if module_name in _ALLOWED_IMPORTS:
        return

    if any(module_name.startswith(f"{allowed}.") for allowed in _ALLOWED_IMPORTS):
        return

    rejections.append(f"disallowed_import: {module_name}")


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        # Ban builtin calls even when referenced through the builtin namespace.
        if isinstance(node.func.value, ast.Name) and node.func.value.id in {"builtins", "__builtins__"}:
            return node.func.attr
        return None
    return None
