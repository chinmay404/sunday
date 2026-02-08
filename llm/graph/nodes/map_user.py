import json
from pathlib import Path

_USER_MAP_PATH = Path(__file__).resolve().parent / "user_map.json"


def map_user(user_id: str) -> str:
    """Map a user_id to a known name."""
    try:
        with open(_USER_MAP_PATH, "r") as f:
            users = json.load(f)
        if user_id in users:
            return users[user_id]
        return "User Not in List Ask for Further Information"
    except Exception as e:
        print(f"Error in Mapping User: {e}")
        return "Unknown"