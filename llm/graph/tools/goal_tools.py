"""Agent tools for goal/plan management."""

import json
from langchain_core.tools import tool

from llm.graph.memory.goals import (
    create_goal as _create_goal,
    add_step as _add_step,
    update_step as _update_step,
    update_goal as _update_goal,
    list_goals as _list_goals,
)


@tool
def create_goal(
    title: str,
    description: str = "",
    priority: int = 5,
    target_date: str = "",
) -> str:
    """Create a goal or objective to track. Use for anything bigger than a quick task.

    Priority: 1 (critical/life-changing) to 10 (someday/maybe).
    Target date: ISO format or empty. Add steps after creating."""
    try:
        result = _create_goal(
            title, description, priority, target_date if target_date else None
        )
        return json.dumps(result)
    except Exception as e:
        return f"Failed: {e}"


@tool
def goal_add_step(goal_id: int, step: str) -> str:
    """Add a step/action to a goal. Steps are auto-ordered. Break big goals into concrete steps."""
    try:
        result = _add_step(goal_id, step)
        return json.dumps(result)
    except Exception as e:
        return f"Failed: {e}"


@tool
def goal_update_step(step_id: int, status: str, blocker: str = "") -> str:
    """Update a goal step. Status: pending, in_progress, done, blocked.
    If blocked, say what's blocking it."""
    try:
        ok = _update_step(step_id, status, blocker if blocker else None)
        return "Step updated." if ok else "Step not found."
    except Exception as e:
        return f"Failed: {e}"


@tool
def update_goal(goal_id: int, status: str = "", title: str = "", priority: int = 0) -> str:
    """Update a goal. Status: active, paused, completed, abandoned."""
    try:
        kwargs = {}
        if status:
            kwargs["status"] = status
        if title:
            kwargs["title"] = title
        if priority > 0:
            kwargs["priority"] = priority
        ok = _update_goal(goal_id, **kwargs)
        return "Goal updated." if ok else "Goal not found or nothing to update."
    except Exception as e:
        return f"Failed: {e}"


@tool
def list_goals(status: str = "active") -> str:
    """List goals with their steps and progress. Status: active, paused, completed, abandoned."""
    try:
        goals = _list_goals(status)
        if not goals:
            return f"No {status} goals."
        return json.dumps(goals, indent=2)
    except Exception as e:
        return f"Failed: {e}"
