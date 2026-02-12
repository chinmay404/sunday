from langchain_core.tools import tool
from llm.services.time_manager import TimeManager

# Initialize the real manager
time_manager = TimeManager()

@tool
def add_calendar_event(summary: str, start_time: str, end_time: str, description: str = ""):
    """Add event to Google Calendar. Times in ISO format (e.g. '2026-01-05T10:00:00')."""
    return time_manager.add_event(summary, start_time, end_time, description)

@tool
def add_todo_item(task: str, due: str = "today"):
    """Add task to Todoist. 'due' can be natural language like 'tomorrow at 10am'."""
    return time_manager.add_task(task, due)

@tool
def list_calendar_events(days_ahead: int = 2):
    """List upcoming Google Calendar events for the next N days (default 2). Returns event summaries, times, and IDs."""
    return time_manager.list_events(days_ahead=days_ahead)

@tool
def delete_calendar_event(event_id: str):
    """Delete a Google Calendar event by its event ID. Use list_calendar_events first to get IDs."""
    return time_manager.delete_event(event_id)

@tool
def list_todo_items(filter_str: str = "today | overdue"):
    """List Todoist tasks. filter_str can be 'today', 'today | overdue', 'all', or any Todoist filter string."""
    return time_manager.list_tasks(filter_str=filter_str)

@tool
def complete_todo_item(task_id: str):
    """Mark a Todoist task as completed. Use list_todo_items first to get task IDs."""
    return time_manager.complete_task(task_id)


def get_time_tools():
    return [add_calendar_event, add_todo_item, list_calendar_events, delete_calendar_event, list_todo_items, complete_todo_item]
