from langchain_core.tools import tool
from llm.services.time_manager import TimeManager

# Initialize the real manager
time_manager = TimeManager()

@tool
def add_calendar_event(summary: str, start_time: str, end_time: str, description: str = ""):
    """
    Add a real event to Google Calendar. 
    Dates must be ISO format (e.g., '2026-01-05T10:00:00').
    """
    return time_manager.add_event(summary, start_time, end_time, description)

@tool
def add_todo_item(task: str, due: str = "today"):
    """
    Add a real task to Todoist. 
    'due' can be natural language like 'tomorrow at 10am' or 'next friday'.
    """
    return time_manager.add_task(task, due)

def get_time_tools():
    return [add_calendar_event, add_todo_item]
