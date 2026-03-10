from execution.safety import validate_custom_workflow_code


def test_allows_from_runtime_import_zoekt_tools() -> None:
    code = """
from runtime import zoekt_tools

repos = zoekt_tools
"""
    assert validate_custom_workflow_code(code) == []


def test_allows_runtime_zoekt_tools_import() -> None:
    code = """
import runtime.zoekt_tools as zoekt_tools

repos = zoekt_tools
"""
    assert validate_custom_workflow_code(code) == []


def test_allows_runtime_github_tools_import() -> None:
    code = """
import runtime.github_tools as github_tools

gh = github_tools
"""
    assert validate_custom_workflow_code(code) == []


def test_rejects_non_zoekt_tools_runtime_from_import() -> None:
    code = """
from runtime import dangerous

x = dangerous
"""
    assert validate_custom_workflow_code(code) == ["disallowed_import: runtime.dangerous"]


def test_allows_top_level_script_without_run_or_main() -> None:
    code = """
import json
from runtime import zoekt_tools

print(json.dumps({"repos": zoekt_tools.list_repos()}, ensure_ascii=True))
"""
    assert validate_custom_workflow_code(code) == []


def test_allows_re_and_safe_stdlib_imports() -> None:
    code = """
import re
from collections import Counter
import math

pattern = re.compile(r"[A-Za-z_]+")
tokens = pattern.findall("alpha beta gamma")
counts = Counter(tokens)
root = math.sqrt(9)
"""
    assert validate_custom_workflow_code(code) == []


def test_rejects_builtins_open_via_attribute() -> None:
    code = """
content = __builtins__.open("x.txt").read()
"""
    assert validate_custom_workflow_code(code) == ["banned_call: open"]
