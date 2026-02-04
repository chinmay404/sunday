import os
import sqlite3
import contextvars
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool

DB_PATH = Path(__file__).resolve().parent / "reminder.db"
CURRENT_CHAT_ID = contextvars.ContextVar("current_telegram_chat_id", default=None)


def set_current_chat_id(chat_id: Optional[str]):
    return CURRENT_CHAT_ID.set(str(chat_id) if chat_id is not None else None)


def reset_current_chat_id(token):
    CURRENT_CHAT_ID.reset(token)


def _parse_time_to_utc_iso(time_text: str) -> str:
    """Parse ISO or natural language time into UTC ISO string."""
    if not isinstance(time_text, str) or not time_text.strip():
        raise ValueError("time must be a non-empty time string.")

    cleaned = time_text.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    local_tz = datetime.now().astimezone().tzinfo

    # 1) Try ISO 8601 first
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        dt = None

    # 2) Fallback to natural language parsing
    if dt is None:
        try:
            import dateparser
        except Exception as exc:
            raise ValueError(
                "Time parsing failed. Install `dateparser` or provide ISO time "
                "like '2026-01-05T10:00:00'."
            ) from exc

        dt = dateparser.parse(
            cleaned,
            settings={
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": str(local_tz) if local_tz else "UTC",
                "PREFER_DATES_FROM": "future",
            },
        )
        if dt is None:
            raise ValueError(
                "Could not parse time. Try a clearer time like "
                "'tomorrow 7pm' or ISO '2026-01-05T10:00:00'."
            )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz or timezone.utc)
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
                note TEXT,
                chat_id TEXT
            )
        """)
        cur.execute("PRAGMA table_info(reminders)")
        cols = {row[1] for row in cur.fetchall()}
        if "chat_id" not in cols:
            cur.execute("ALTER TABLE reminders ADD COLUMN chat_id TEXT")
        conn.commit()
    
    




def _create_reminder(time_iso: str, message: str, note: str = "", chat_id: Optional[str] = None):
    init_db()
    normalized_time = _parse_time_to_utc_iso(time_iso)
    effective_chat_id = chat_id or CURRENT_CHAT_ID.get() or os.getenv("TELEGRAM_CHAT_ID")
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reminders (time, message, note, chat_id) VALUES (?, ?, ?, ?)",
            (normalized_time, message, note or None, str(effective_chat_id) if effective_chat_id else None)
        )
        reminder_id = cur.lastrowid
        conn.commit()

    return {
        "id": reminder_id,
        "time": normalized_time,
        "message": message,
        "status": "scheduled",
        "note": note or None,
        "chat_id": str(effective_chat_id) if effective_chat_id else None
    }


@tool
def create_reminder(time_iso: str, message: str, note: str = "", chat_id: Optional[str] = None):
    """Create a reminder at a specific time (ISO or natural language). Stored as UTC."""
    return _create_reminder(time_iso, message, note, chat_id)
    
    
@tool
def list_reminders():
    """List all scheduled reminders."""
    init_db()
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, time, message, note, chat_id FROM reminders WHERE status='scheduled' ORDER BY time ASC"
        )
        rows = cur.fetchall()

    return [
        {"id": r[0], "time": r[1], "message": r[2], "note": r[3], "chat_id": r[4]}
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
