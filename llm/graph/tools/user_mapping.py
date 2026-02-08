import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

_USER_MAP_PATH = Path(__file__).resolve().parents[2] / "nodes" / "user_map.json"


def _load_user_map() -> dict:
    try:
        with open(_USER_MAP_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_user_map(data: dict) -> None:
    with open(_USER_MAP_PATH, "w") as f:
        json.dump(data, f, indent=2)


@tool
def add_user_in_known_user(user_id: str, user_name: str, description: Optional[str] = None):
    """Add a person to known users list."""
    try:
        users = _load_user_map()
        if user_id in users:
            return f"User already known as {users[user_id]}"
        users[user_id] = user_name
        _save_user_map(users)
        return f"User {user_name} added successfully."
    except Exception as e:
        print(f"Error adding user: {e}")
        return "Error adding user."


@tool
def map_user(user_id: str):
    """Look up who a user_id belongs to."""
    users = _load_user_map()
    if user_id in users:
        return users[user_id]
    return "User not in list. Ask for further information."


@tool
def add_thing_to_remeber(user_id: str, thing: str):
    """Save a note/thing to remember for a user."""
    try:
        users = _load_user_map()
        if user_id not in users:
            return "User not in list. Add them first."
        # Ensure user entry is a dict for storing extras
        entry = users[user_id]
        if isinstance(entry, str):
            entry = {"name": entry, "remember": []}
        if "remember" not in entry:
            entry["remember"] = []
        entry["remember"].append(thing)
        users[user_id] = entry
        _save_user_map(users)
        return f"Saved for {user_id}."
    except Exception as e:
        print(f"Error saving thing to remember: {e}")
        return "Error saving."