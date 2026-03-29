from pathlib import Path

import pytest

from src.skills.registry import SkillRegistry, SkillRegistryError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_skill_registry_loads_current_skills() -> None:
    registry = SkillRegistry(SRC_ROOT / "skills")

    assert "views.list_capabilities" in registry.views
    assert "views.runtime_helpers" in registry.views
    assert "execution.run_custom_workflow_code" in registry.capabilities
    assert "runtime.search" in registry.runtime_helpers
    assert "list_capabilities" in registry.tools

    header = registry.render_view_header("views.list_capabilities", total=10)
    assert "## Capability List" in header
    assert "- Total: `10`" in header


def test_skill_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write(
        skills_root / "views" / "a.md",
        """---
id: duplicate.id
doc_type: view
---

--- list_capabilities ---
alpha
""",
    )
    _write(
        skills_root / "tools" / "b.md",
        """---
id: duplicate.id
doc_type: tool
---

Tool description.
""",
    )

    with pytest.raises(SkillRegistryError, match="duplicate skill id"):
        SkillRegistry(skills_root)


def test_skill_registry_rejects_bad_frontmatter(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write(
        skills_root / "views" / "bad.md",
        """---
id: [broken
doc_type: view
---

--- list_capabilities ---
text
""",
    )

    with pytest.raises(SkillRegistryError, match="invalid frontmatter yaml"):
        SkillRegistry(skills_root)


def test_skill_registry_rejects_missing_required_sections(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write(
        skills_root / "capabilities" / "cap.md",
        """---
id: cap.one
doc_type: capability
kind: workflow
order: 1
execution:
  script_path: skills/workflows/scripts/symbol_usage.py
  arg_schema: {}
---

--- list_capabilities ---
- Summary: x
""",
    )

    with pytest.raises(SkillRegistryError, match="missing required section"):
        SkillRegistry(skills_root)
