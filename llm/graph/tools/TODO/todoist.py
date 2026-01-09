"""
Simple Todoist CRUD Tool
Handles Create, Read, Update, Delete operations for tasks and projects
"""

import os
from todoist_api_python.api import TodoistAPI
from typing import Optional, List, Dict


class TodoistManager:
    """Simple manager for Todoist tasks and projects"""

    def __init__(self, api_token: Optional[str] = None):
        """Initialize with API token from parameter or environment"""
        # token = api_token or os.getenv("TODOIST_API_TOKEN")
        token = "b4eaf942726470d112d0c12cb95e828931b1d177"
        if not token:
            raise ValueError("TODOIST_API_TOKEN not found in environment")
        self.api = TodoistAPI(token)

    # ========== TASK OPERATIONS ==========

    def create_task(self, content: str, project_id: Optional[str] = None,
                    description: Optional[str] = None, due_string: Optional[str] = None,
                    priority: int = 1) -> Dict:
        """
        Create a new task

        Args:
            content: Task title/content
            project_id: Optional project ID to add task to
            description: Optional task description
            due_string: Natural language due date (e.g., "tomorrow", "next Monday")
            priority: Priority 1-4 (4 is highest)

        Returns:
            Created task as dictionary
        """
        try:
            task = self.api.add_task(
                content=content,
                project_id=project_id,
                description=description,
                due_string=due_string,
                priority=priority
            )
            print(f"✓ Created task: {task.content}")
            return task.to_dict()
        except Exception as e:
            print(f"✗ Error creating task: {e}")
            raise

    def get_task(self, task_id: str) -> Dict:
        """
        Get a specific task by ID

        Args:
            task_id: Task ID

        Returns:
            Task as dictionary
        """
        try:
            task = self.api.get_task(task_id)
            return task.to_dict()
        except Exception as e:
            print(f"✗ Error getting task: {e}")
            raise

    def get_all_tasks(self, project_id: Optional[str] = None) -> List[Dict]:
        """
        Get all active tasks, optionally filtered by project

        Args:
            project_id: Optional project ID to filter by

        Returns:
            List of tasks as dictionaries
        """
        try:
            tasks = self.api.get_tasks(project_id=project_id)
            # Handle different return types from API
            result = []
            for item in tasks:
                if isinstance(item, list):
                    # If it's a list, extend our result
                    result.extend([t.to_dict() if hasattr(
                        t, 'to_dict') else t for t in item])
                elif hasattr(item, 'to_dict'):
                    # If it's a task object, convert it
                    result.append(item.to_dict())
                elif isinstance(item, dict):
                    # If it's already a dict, use it
                    result.append(item)
            return result
        except Exception as e:
            print(f"✗ Error getting tasks: {e}")
            raise

    def update_task(self, task_id: str, content: Optional[str] = None,
                    description: Optional[str] = None, due_string: Optional[str] = None,
                    priority: Optional[int] = None) -> Dict:
        """
        Update an existing task

        Args:
            task_id: Task ID to update
            content: New task content
            description: New description
            due_string: New due date
            priority: New priority (1-4)

        Returns:
            Updated task as dictionary
        """
        try:
            # Build update parameters (only include non-None values)
            update_params = {}
            if content is not None:
                update_params['content'] = content
            if description is not None:
                update_params['description'] = description
            if due_string is not None:
                update_params['due_string'] = due_string
            if priority is not None:
                update_params['priority'] = priority

            success = self.api.update_task(task_id=task_id, **update_params)
            if success:
                print(f"✓ Updated task: {task_id}")
                return self.get_task(task_id)
            else:
                raise Exception("Update failed")
        except Exception as e:
            print(f"✗ Error updating task: {e}")
            raise

    def complete_task(self, task_id: str) -> bool:
        """
        Mark a task as complete

        Args:
            task_id: Task ID to complete

        Returns:
            True if successful
        """
        try:
            success = self.api.complete_task(task_id)
            if success:
                print(f"✓ Completed task: {task_id}")
            return success
        except Exception as e:
            print(f"✗ Error completing task: {e}")
            raise

    def reopen_task(self, task_id: str) -> bool:
        """
        Reopen a completed task (undone)

        Args:
            task_id: Task ID to reopen

        Returns:
            True if successful
        """
        try:
            success = self.api.uncomplete_task(task_id)
            if success:
                print(f"✓ Reopened task: {task_id}")
            return success
        except Exception as e:
            print(f"✗ Error reopening task: {e}")
            raise

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task permanently

        Args:
            task_id: Task ID to delete

        Returns:
            True if successful
        """
        try:
            success = self.api.delete_task(task_id)
            if success:
                print(f"✓ Deleted task: {task_id}")
            return success
        except Exception as e:
            print(f"✗ Error deleting task: {e}")
            raise

    # ========== PROJECT OPERATIONS ==========

    def create_project(self, name: str, color: Optional[str] = None,
                       is_favorite: bool = False) -> Dict:
        """
        Create a new project

        Args:
            name: Project name
            color: Optional color (e.g., "red", "blue")
            is_favorite: Mark as favorite

        Returns:
            Created project as dictionary
        """
        try:
            project = self.api.add_project(
                name=name,
                color=color,
                is_favorite=is_favorite
            )
            print(f"✓ Created project: {project.name}")
            return project.to_dict()
        except Exception as e:
            print(f"✗ Error creating project: {e}")
            raise

    def get_project(self, project_id: str) -> Dict:
        """
        Get a specific project by ID

        Args:
            project_id: Project ID

        Returns:
            Project as dictionary
        """
        try:
            project = self.api.get_project(project_id)
            return project.to_dict()
        except Exception as e:
            print(f"✗ Error getting project: {e}")
            raise

    def get_all_projects(self) -> List[Dict]:
        """
        Get all projects

        Returns:
            List of projects as dictionaries
        """
        try:
            projects = self.api.get_projects()
            # Handle different return types from API
            result = []
            for item in projects:
                if isinstance(item, list):
                    # If it's a list, extend our result
                    result.extend([p.to_dict() if hasattr(
                        p, 'to_dict') else p for p in item])
                elif hasattr(item, 'to_dict'):
                    # If it's a project object, convert it
                    result.append(item.to_dict())
                elif isinstance(item, dict):
                    # If it's already a dict, use it
                    result.append(item)
            return result
        except Exception as e:
            print(f"✗ Error getting projects: {e}")
            raise

    def update_project(self, project_id: str, name: Optional[str] = None,
                       color: Optional[str] = None, is_favorite: Optional[bool] = None) -> Dict:
        """
        Update an existing project

        Args:
            project_id: Project ID to update
            name: New project name
            color: New color
            is_favorite: New favorite status

        Returns:
            Updated project as dictionary
        """
        try:
            # Build update parameters
            update_params = {}
            if name is not None:
                update_params['name'] = name
            if color is not None:
                update_params['color'] = color
            if is_favorite is not None:
                update_params['is_favorite'] = is_favorite

            success = self.api.update_project(
                project_id=project_id, **update_params)
            if success:
                print(f"✓ Updated project: {project_id}")
                return self.get_project(project_id)
            else:
                raise Exception("Update failed")
        except Exception as e:
            print(f"✗ Error updating project: {e}")
            raise

    def delete_project(self, project_id: str) -> bool:
        """
        Delete a project permanently

        Args:
            project_id: Project ID to delete

        Returns:
            True if successful
        """
        try:
            success = self.api.delete_project(project_id)
            if success:
                print(f"✓ Deleted project: {project_id}")
            return success
        except Exception as e:
            print(f"✗ Error deleting project: {e}")
            raise

    # ========== HELPER METHODS ==========

    def print_tasks(self, tasks: List[Dict]) -> None:
        """Pretty print a list of tasks"""
        if not tasks:
            print("No tasks found")
            return

        print(f"\n{'='*60}")
        print(f"Found {len(tasks)} task(s)")
        print(f"{'='*60}")

        for task in tasks:
            priority_icons = {1: "○", 2: "◐", 3: "◑", 4: "●"}
            priority = task.get('priority', 1)
            icon = priority_icons.get(priority, "○")

            print(f"\n{icon} {task.get('content', 'Untitled')}")
            print(f"  ID: {task.get('id')}")
            if task.get('description'):
                print(f"  Description: {task.get('description')}")
            if task.get('due'):
                print(f"  Due: {task.get('due', {}).get('string', 'N/A')}")
            if task.get('project_id'):
                print(f"  Project: {task.get('project_id')}")

        print(f"\n{'='*60}\n")

    def print_projects(self, projects: List[Dict]) -> None:
        """Pretty print a list of projects"""
        if not projects:
            print("No projects found")
            return

        print(f"\n{'='*60}")
        print(f"Found {len(projects)} project(s)")
        print(f"{'='*60}")

        for project in projects:
            fav = "★ " if project.get('is_favorite') else ""
            print(f"\n{fav}{project.get('name', 'Untitled')}")
            print(f"  ID: {project.get('id')}")
            if project.get('color'):
                print(f"  Color: {project.get('color')}")

        print(f"\n{'='*60}\n")


# ========== EXAMPLE USAGE ==========

def main():
    """Example usage of TodoistManager"""

    # Initialize manager
    manager = TodoistManager()

    print("=== TODOIST CRUD DEMO ===\n")

    # Create a project
    print("1. Creating a project...")
    project = manager.create_project(
        name="Demo Project",
        color="blue",
        is_favorite=True
    )
    project_id = project['id']

    # Create tasks
    print("\n2. Creating tasks...")
    task1 = manager.create_task(
        content="Buy groceries",
        project_id=project_id,
        description="Milk, eggs, bread",
        due_string="today",
        priority=3
    )

    task2 = manager.create_task(
        content="Write report",
        project_id=project_id,
        due_string="tomorrow",
        priority=4
    )

    # Get all tasks
    print("\n3. Getting all tasks...")
    all_tasks = manager.get_all_tasks(project_id=project_id)
    manager.print_tasks(all_tasks)

    # Update a task
    print("\n4. Updating task...")
    manager.update_task(
        task_id=task1['id'],
        content="Buy groceries and supplies",
        priority=4
    )

    # Complete a task
    print("\n5. Completing task...")
    manager.complete_task(task2['id'])

    # Reopen task
    print("\n6. Reopening task...")
    manager.reopen_task(task2['id'])

    # Get all projects
    print("\n7. Getting all projects...")
    all_projects = manager.get_all_projects()
    manager.print_projects(all_projects)

    # Cleanup (optional - uncomment to delete)
    # print("\n8. Cleanup...")
    # manager.delete_task(task1['id'])
    # manager.delete_task(task2['id'])
    # manager.delete_project(project_id)

    print("\n=== DEMO COMPLETE ===")


if __name__ == "__main__":
    main()
