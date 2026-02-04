# scheduler.py
import sys
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from langchain_core.messages import HumanMessage

try:
    from .weakup_tools import DB_PATH, init_db
except ImportError:
    # Fallback when running as a script directly
    from weakup_tools import DB_PATH, init_db

POLL_INTERVAL = 30  # seconds


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _build_reminder_message(message: str, note: Optional[str]) -> str:
    if note:
        return f"Reminder: {message}\nNote: {note}"
    return f"Reminder: {message}"


def run_scheduler(poll_interval: int = POLL_INTERVAL) -> None:
    # Ensure project root is on sys.path for absolute imports
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from llm.graph.graph import create_graph

    init_db()
    graph = create_graph()

    while True:
        now = _utc_now_iso()
        with sqlite3.connect(str(DB_PATH)) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, time, message, note FROM reminders
                WHERE status='scheduled' AND time <= ?
                ORDER BY time ASC
            """, (now,))
            due = cur.fetchall()

            for reminder_id, _time_iso, message, note in due:
                reminder_text = _build_reminder_message(message, note)
                initial_state = {"messages": [HumanMessage(content=reminder_text)]}
                try:
                    graph.invoke(
                        initial_state,
                        config={"configurable": {"thread_id": f"reminder-{reminder_id}"}}
                    )
                    cur.execute(
                        "UPDATE reminders SET status='done' WHERE id=?",
                        (reminder_id,)
                    )
                except Exception as exc:
                    print(f"Error sending reminder {reminder_id}: {exc}")

            conn.commit()
        time.sleep(poll_interval)


if __name__ == "__main__":
    run_scheduler()
