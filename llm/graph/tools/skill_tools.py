"""Agent tools for the skill library."""

import json
from langchain_core.tools import tool

from llm.graph.skills.runner import list_available_skills, get_skill_playbook


@tool
def list_skills() -> str:
    """List all available skills/routines. Skills are predefined playbooks for complex tasks like weekly reviews, brain dumps, meeting prep, etc."""
    try:
        skills = list_available_skills()
        if not skills:
            return "No skills available."
        return json.dumps(skills, indent=2)
    except Exception as e:
        return f"Failed: {e}"


@tool
def run_skill(skill_name: str, context: str = "") -> str:
    """Run a skill/routine by name. Returns step-by-step instructions to execute.

    Use list_skills first to see what's available.
    Context: any relevant info (e.g., which meeting, what the brain dump is about)."""
    try:
        playbook = get_skill_playbook(skill_name, context)
        if not playbook:
            available = list_available_skills()
            names = [s["name"] for s in available]
            return f"Skill '{skill_name}' not found. Available: {', '.join(names) if names else 'none'}"
        return playbook
    except Exception as e:
        return f"Failed: {e}"
