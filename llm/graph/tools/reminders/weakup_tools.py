import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from langchain_core.tools import tool

DB_PATH = Path(__file__).resolve().parent / "reminder.db"


def _normalize_iso_time(time_iso: str) -> str:
    """Normalize ISO time to UTC with seconds precision."""
    if not isinstance(time_iso, str) or not time_iso.strip():
        raise ValueError("time_iso must be a non-empty ISO 8601 string.")
    cleaned = time_iso.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(
            "time_iso must be ISO 8601 like '2026-01-05T10:00:00' or "
            "'2026-01-05T10:00:00+00:00'."
        ) from exc

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt.replace(microsecond=0).isoformat()


def init_db():
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled',
                note TEXT
            )
        """)
        conn.commit()
    
    




def _create_reminder(time_iso: str, message: str, note: str = ""):
    init_db()
    normalized_time = _normalize_iso_time(time_iso)
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reminders (time, message, note) VALUES (?, ?, ?)",
            (normalized_time, message, note or None)
        )
        reminder_id = cur.lastrowid
        conn.commit()

    return {
        "id": reminder_id,
        "time": normalized_time,
        "message": message,
        "status": "scheduled",
        "note": note or None
    }


@tool
def create_reminder(time_iso: str, message: str, note: str = ""):
    """Create a reminder at ISO time (stored as UTC)."""
    return _create_reminder(time_iso, message, note)
    
    
@tool
def list_reminders():
    """List all scheduled reminders."""
    init_db()
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, time, message, note FROM reminders WHERE status='scheduled' ORDER BY time ASC"
        )
        rows = cur.fetchall()

    return [
        {"id": r[0], "time": r[1], "message": r[2], "note": r[3]}
        for r in rows
    ]
    


@tool
def cancel_reminder(reminder_id: int):
    """Cancel a reminder by ID."""
    init_db()
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE reminders SET status='cancelled' WHERE id=?",
            (reminder_id,)
        )
        conn.commit()

    return {
        "id": reminder_id,
        "status": "cancelled"
    }
