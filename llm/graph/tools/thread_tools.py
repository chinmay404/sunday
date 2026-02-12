"""Agent tools for thread/commitment tracking."""

import json
from langchain_core.tools import tool

from llm.graph.memory.threads import (
    create_thread as _create,
    resolve_thread as _resolve,
    update_thread as _update,
    list_threads as _list,
)


@tool
def create_thread(
    title: str,
    thread_type: str = "follow_up",
    context: str = "",
    priority: int = 5,
    due_date: str = "",
) -> str:
    """Track an open loop — a commitment, worry, question, follow-up, or waiting-on item.

    Types: commitment, worry, question, follow_up, waiting_on, idea
    Priority: 1 (urgent) to 10 (low). Due date: ISO format or empty.
    Use this whenever something feels unfinished or needs follow-up."""
    try:
        result = _create(
            title,
            thread_type,
            context,
            priority,
            due_date if due_date else None,
        )
        return json.dumps(result)
    except Exception as e:
        return f"Failed to create thread: {e}"


@tool
def resolve_thread(thread_id: int, resolution: str = "") -> str:
    """Mark a thread as resolved. Optionally note how it was resolved."""
    try:
        ok = _resolve(thread_id, resolution)
        return "Thread resolved." if ok else "Thread not found."
    except Exception as e:
        return f"Failed: {e}"


@tool
def list_threads(status: str = "open") -> str:
    """List tracked threads/commitments/worries. Status: open, waiting, resolved, abandoned."""
    try:
        threads = _list(status)
        if not threads:
            return f"No {status} threads."
        return json.dumps(threads, indent=2)
    except Exception as e:
        return f"Failed: {e}"


@tool
def bump_thread(thread_id: int, note: str = "", priority: int = 0) -> str:
    """Update a thread — add context/notes or change priority."""
    try:
        kwargs = {}
        if note:
            kwargs["context"] = note
        if priority > 0:
            kwargs["priority"] = priority
        ok = _update(thread_id, **kwargs)
        return "Thread updated." if ok else "Thread not found or nothing to update."
    except Exception as e:
        return f"Failed: {e}"
