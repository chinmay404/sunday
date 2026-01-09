"""
Todoist tools for LangChain integration
Provides CRUD operations for tasks and projects
"""

from langchain_core.tools import tool
from .todoist import TodoistManager
from typing import Optional


# Initialize the Todoist manager once
_manager = TodoistManager()


# ========== TASK TOOLS ==========

@tool
def create_todo_task(content: str, project_id: Optional[str] = None,
                     description: Optional[str] = None, due_string: Optional[str] = None,
                     priority: int = 1) -> str:
    """Create a new TODO task in Todoist.

    Args:
        content: Task title/content (required)
        project_id: Optional project ID to add task to
        description: Optional task description
        due_string: Natural language due date (e.g., "tomorrow", "next Monday", "in 3 days")
        priority: Priority 1-4 where 4 is highest (default: 1)

    Returns:
        Success message with task details
    """
    try:
        task = _manager.create_task(
            content=content,
            project_id=project_id,
            description=description,
            due_string=due_string,
            priority=priority
        )
        return f"✓ Created task: '{task['content']}' (ID: {task['id']})"
    except Exception as e:
        return f"✗ Failed to create task: {str(e)}"


@tool
def get_todo_tasks(project_id: Optional[str] = None) -> str:
    """Get all active TODO tasks, optionally filtered by project.

    Args:
        project_id: Optional project ID to filter tasks by

    Returns:
        List of tasks with details
    """
    try:
        tasks = _manager.get_all_tasks(project_id=project_id)
        if not tasks:
            return "No tasks found"

        result = f"Found {len(tasks)} task(s):\n\n"
        for task in tasks:
            priority_icons = {1: "○", 2: "◐", 3: "◑", 4: "●"}
            icon = priority_icons.get(task.get('priority', 1), "○")
            result += f"{icon} {task.get('content', 'Untitled')}\n"
            result += f"  ID: {task.get('id')}\n"
            if task.get('description'):
                result += f"  Description: {task.get('description')}\n"
            if task.get('due'):
                result += f"  Due: {task.get('due', {}).get('string', 'N/A')}\n"
            result += "\n"

        return result
    except Exception as e:
        return f"✗ Failed to get tasks: {str(e)}"


@tool
def update_todo_task(task_id: str, content: Optional[str] = None,
                     description: Optional[str] = None, due_string: Optional[str] = None,
                     priority: Optional[int] = None) -> str:
    """Update an existing TODO task.

    Args:
        task_id: Task ID to update (required)
        content: New task content
        description: New description
        due_string: New due date (natural language)
        priority: New priority (1-4)

    Returns:
        Success message with updated task details
    """
    try:
        task = _manager.update_task(
            task_id=task_id,
            content=content,
            description=description,
            due_string=due_string,
            priority=priority
        )
        return f"✓ Updated task: '{task['content']}' (ID: {task['id']})"
    except Exception as e:
        return f"✗ Failed to update task: {str(e)}"


@tool
def complete_todo_task(task_id: str) -> str:
    """Mark a TODO task as complete.

    Args:
        task_id: Task ID to complete (required)

    Returns:
        Success message
    """
    try:
        success = _manager.complete_task(task_id)
        if success:
            return f"✓ Completed task: {task_id}"
        return f"✗ Failed to complete task: {task_id}"
    except Exception as e:
        return f"✗ Failed to complete task: {str(e)}"


@tool
def reopen_todo_task(task_id: str) -> str:
    """Reopen a completed TODO task (undone).

    Args:
        task_id: Task ID to reopen (required)

    Returns:
        Success message
    """
    try:
        success = _manager.reopen_task(task_id)
        if success:
            return f"✓ Reopened task: {task_id}"
        return f"✗ Failed to reopen task: {task_id}"
    except Exception as e:
        return f"✗ Failed to reopen task: {str(e)}"


@tool
def delete_todo_task(task_id: str) -> str:
    """Delete a TODO task permanently.

    Args:
        task_id: Task ID to delete (required)

    Returns:
        Success message
    """
    try:
        success = _manager.delete_task(task_id)
        if success:
            return f"✓ Deleted task: {task_id}"
        return f"✗ Failed to delete task: {task_id}"
    except Exception as e:
        return f"✗ Failed to delete task: {str(e)}"


# ========== PROJECT TOOLS ==========

@tool
def create_todo_project(name: str, color: Optional[str] = None,
                        is_favorite: bool = False) -> str:
    """Create a new TODO project in Todoist.

    Args:
        name: Project name (required)
        color: Optional color (e.g., "red", "blue", "green")
        is_favorite: Mark as favorite (default: False)

    Returns:
        Success message with project details
    """
    try:
        project = _manager.create_project(
            name=name,
            color=color,
            is_favorite=is_favorite
        )
        return f"✓ Created project: '{project['name']}' (ID: {project['id']})"
    except Exception as e:
        return f"✗ Failed to create project: {str(e)}"


@tool
def get_todo_projects() -> str:
    """Get all TODO projects.

    Returns:
        List of projects with details
    """
    try:
        projects = _manager.get_all_projects()
        if not projects:
            return "No projects found"

        result = f"Found {len(projects)} project(s):\n\n"
        for project in projects:
            fav = "★ " if project.get('is_favorite') else ""
            result += f"{fav}{project.get('name', 'Untitled')}\n"
            result += f"  ID: {project.get('id')}\n"
            if project.get('color'):
                result += f"  Color: {project.get('color')}\n"
            result += "\n"

        return result
    except Exception as e:
        return f"✗ Failed to get projects: {str(e)}"


@tool
def update_todo_project(project_id: str, name: Optional[str] = None,
                        color: Optional[str] = None, is_favorite: Optional[bool] = None) -> str:
    """Update an existing TODO project.

    Args:
        project_id: Project ID to update (required)
        name: New project name
        color: New color
        is_favorite: New favorite status

    Returns:
        Success message with updated project details
    """
    try:
        project = _manager.update_project(
            project_id=project_id,
            name=name,
            color=color,
            is_favorite=is_favorite
        )
        return f"✓ Updated project: '{project['name']}' (ID: {project['id']})"
    except Exception as e:
        return f"✗ Failed to update project: {str(e)}"


@tool
def delete_todo_project(project_id: str) -> str:
    """Delete a TODO project permanently.

    Args:
        project_id: Project ID to delete (required)

    Returns:
        Success message
    """
    try:
        success = _manager.delete_project(project_id)
        if success:
            return f"✓ Deleted project: {project_id}"
        return f"✗ Failed to delete project: {project_id}"
    except Exception as e:
        return f"✗ Failed to delete project: {str(e)}"
