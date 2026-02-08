import os
import contextvars
from datetime import datetime, timezone
from typing import Optional
from langchain_core.tools import tool
from llm.graph.db import get_connection

CURRENT_CHAT_ID = contextvars.ContextVar("current_telegram_chat_id", default=None)
SELF_WAKEUP_NOTE_PREFIX = "[SELF_WAKEUP_REASON]"


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
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reminders (
                        id SERIAL PRIMARY KEY,
                        time TIMESTAMPTZ NOT NULL,
                        message TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'scheduled',
                        note TEXT,
                        chat_id TEXT
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_reminders_status_time ON reminders(status, time)"
                )
    finally:
        conn.close()

def _create_reminder(time_iso: str, message: str, note: str = "", chat_id: Optional[str] = None):
    init_db()
    normalized_time = _parse_time_to_utc_iso(time_iso)
    effective_chat_id = chat_id or CURRENT_CHAT_ID.get() or os.getenv("TELEGRAM_CHAT_ID")
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO reminders (time, message, note, chat_id) VALUES (%s, %s, %s, %s) RETURNING id",
                    (
                        normalized_time,
                        message,
                        note or None,
                        str(effective_chat_id) if effective_chat_id else None,
                    ),
                )
                reminder_id = cur.fetchone()[0]
    finally:
        conn.close()

    return {
        "id": reminder_id,
        "time": normalized_time,
        "message": message,
        "status": "scheduled",
        "note": note or None,
        "chat_id": str(effective_chat_id) if effective_chat_id else None
    }


def _encode_self_wakeup_note(reason: str) -> str:
    reason_text = (reason or "").strip()
    return f"{SELF_WAKEUP_NOTE_PREFIX} {reason_text}".strip()


def _decode_self_wakeup_reason(note: Optional[str]) -> Optional[str]:
    if not isinstance(note, str):
        return None
    stripped = note.strip()
    if not stripped.startswith(SELF_WAKEUP_NOTE_PREFIX):
        return None
    return stripped[len(SELF_WAKEUP_NOTE_PREFIX):].strip() or None


@tool
def create_reminder(time_iso: str, message: str, note: str = "", chat_id: Optional[str] = None):
    """Create a reminder at a specific time (ISO or natural language). Stored as UTC."""
    return _create_reminder(time_iso, message, note, chat_id)
    
    
@tool
def list_reminders():
    """List all scheduled reminders."""
    init_db()
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, time, message, note, chat_id FROM reminders WHERE status='scheduled' ORDER BY time ASC"
                )
                rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": r[0],
            "time": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
            "message": r[2],
            "note": r[3],
            "self_wakeup_reason": _decode_self_wakeup_reason(r[3]),
            "chat_id": r[4],
        }
        for r in rows
    ]



@tool
def cancel_reminder(reminder_id: int):
    """Cancel a reminder by ID."""
    init_db()
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE reminders SET status='cancelled' WHERE id=%s",
                    (reminder_id,),
                )
    finally:
        conn.close()

    return {
        "id": reminder_id,
        "status": "cancelled"
    }


@tool
def schedule_self_wakeup(
    time_iso: str,
    reason: str,
    check_in_message: str = "Check in with Chinmay now.",
    chat_id: Optional[str] = None,
):
    """
    Schedule a proactive wake-up/check-in decided by Sunday.
    Stores the reason so the scheduler can pass it back into the agent at trigger time.
    """
    reason_text = (reason or "").strip()
    if not reason_text:
        raise ValueError("reason is required.")

    message_text = (check_in_message or "").strip() or "Check in with Chinmay now."
    reminder = _create_reminder(
        time_iso=time_iso,
        message=message_text,
        note=_encode_self_wakeup_note(reason_text),
        chat_id=chat_id,
    )
    reminder["kind"] = "self_wakeup"
    reminder["reason"] = reason_text
    return reminder
