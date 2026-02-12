"""
Skill Library — YAML-driven routines for Sunday.

== HOW TO ADD A SKILL ==

1. Create a YAML file in llm/graph/skills/definitions/
2. Follow this format:

    name: my_skill
    description: "What this skill does (shown to agent)"
    trigger_hint: "keywords or phrases that might trigger this skill"
    steps:
      - "Step 1: do this thing"
      - "Step 2: then do this"
    tools_hint:
      - search_memory
      - list_goals
    output_format: "How the result should look"
    notes: "Extra context for the agent"

3. That's it. No code changes needed.

The agent calls `run_skill("my_skill")` and gets the playbook returned as
instructions it follows naturally using its existing tools.

== HOW TO REMOVE A SKILL ==
Delete the YAML file. Done.

== HOW TO UPDATE A SKILL ==
Edit the YAML file. Changes take effect immediately (skills are loaded fresh each time).
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

_DEFINITIONS_DIR = Path(__file__).parent / "definitions"

# Support both yaml and json for flexibility
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False
    logger.warning("PyYAML not installed — skills will use JSON fallback")

try:
    import json
except ImportError:
    pass


def _load_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load a skill definition from YAML or JSON."""
    try:
        with open(path) as fh:
            if path.suffix in (".yaml", ".yml"):
                if _HAS_YAML:
                    return yaml.safe_load(fh)
                else:
                    logger.warning("Cannot load %s without PyYAML", path.name)
                    return None
            elif path.suffix == ".json":
                return json.load(fh)
    except Exception as e:
        logger.warning("Failed to load skill %s: %s", path.name, e)
    return None


def _load_all_skills() -> Dict[str, Dict[str, Any]]:
    """Load all skill definitions from the definitions/ directory."""
    skills: Dict[str, Dict[str, Any]] = {}
    if not _DEFINITIONS_DIR.exists():
        return skills

    for ext in ("*.yaml", "*.yml", "*.json"):
        for f in _DEFINITIONS_DIR.glob(ext):
            data = _load_file(f)
            if data and "name" in data:
                skills[data["name"]] = data

    return skills


def list_available_skills() -> List[Dict[str, str]]:
    """Return name + description for all available skills."""
    skills = _load_all_skills()
    return [
        {
            "name": s["name"],
            "description": s.get("description", ""),
            "trigger_hint": s.get("trigger_hint", ""),
        }
        for s in skills.values()
    ]


def get_skill_playbook(skill_name: str, user_context: str = "") -> Optional[str]:
    """
    Build an instruction playbook for a skill.

    Returns a formatted prompt the agent can follow using its existing tools.
    This is the magic — the skill is just structured instructions,
    and the LLM already has all the tools to execute them.
    """
    skills = _load_all_skills()
    skill = skills.get(skill_name)
    if not skill:
        return None

    lines = [f"## SKILL: {skill['name']}"]

    if skill.get("description"):
        lines.append(f"**Purpose**: {skill['description']}")
    lines.append("")

    if user_context:
        lines.append(f"**User context**: {user_context}")
        lines.append("")

    if skill.get("steps"):
        lines.append("**Follow these steps in order:**")
        for i, step in enumerate(skill["steps"], 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    if skill.get("tools_hint"):
        lines.append(f"**Tools you'll likely need**: {', '.join(skill['tools_hint'])}")
        lines.append("")

    if skill.get("output_format"):
        lines.append(f"**Output style**: {skill['output_format']}")

    if skill.get("notes"):
        lines.append(f"\n**Notes**: {skill['notes']}")

    return "\n".join(lines)
