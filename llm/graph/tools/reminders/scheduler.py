# scheduler.py
import sys
import time
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv
from llm.graph.db import get_connection

try:
    from .weakup_tools import (
        init_db,
        set_current_chat_id,
        reset_current_chat_id,
        _decode_self_wakeup_reason,
    )
except ImportError:
    # Fallback when running as a script directly
    from weakup_tools import (
        init_db,
        set_current_chat_id,
        reset_current_chat_id,
        _decode_self_wakeup_reason,
    )

POLL_INTERVAL = 30  # seconds


def _should_enable_scheduler() -> bool:
    flag = os.getenv("REMINDER_SCHEDULER_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _build_reminder_event(reminder_id: int, message: str, note: Optional[str]) -> str:
    self_wakeup_reason = _decode_self_wakeup_reason(note)
    if self_wakeup_reason:
        return (
            "Wake-up trigger reached.\n"
            f"Reminder ID: {reminder_id}\n"
            f"Check-in objective: {message}\n"
            f"Reason set earlier: {self_wakeup_reason}\n"
            "Respond to Chinmay naturally and continue the same conversation."
        )
    if note:
        return f"Reminder trigger reached.\nReminder: {message}\nNote: {note}"
    return f"Reminder trigger reached.\nReminder: {message}"


def _extract_last_ai_text(result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not last_ai:
        return ""
    content = getattr(last_ai, "content", "")
    if isinstance(content, list):
        return "\n".join(str(part) for part in content if part is not None).strip()
    return str(content).strip()


def run_scheduler(
    poll_interval: int = POLL_INTERVAL,
    graph=None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    # Ensure project root is on sys.path for absolute imports
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from integrations.telegram.send_telegram import send_message

    load_dotenv(root_dir / ".env")
    if not _should_enable_scheduler():
        print("Reminder scheduler disabled via REMINDER_SCHEDULER_ENABLE.")
        return

    telegram_token = os.getenv("TELEGRAM_API_TOKEN")
    default_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    init_db()
    if graph is None:
        from llm.graph.graph import create_graph
        graph = create_graph()

    while True:
        if stop_event and stop_event.is_set():
            print("Reminder scheduler stopping...")
            break

        now = _utc_now_iso()
        conn = get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, time, message, note, chat_id FROM reminders
                        WHERE status='scheduled' AND time <= %s
                        ORDER BY time ASC
                        """,
                        (now,),
                    )
                    due = cur.fetchall()

                    for reminder_id, _time_iso, message, note, chat_id in due:
                        reminder_text = _build_reminder_event(reminder_id, message, note)
                        target_chat_id = str(chat_id) if chat_id else (str(default_chat_id) if default_chat_id else None)
                        thread_id = target_chat_id or f"reminder-{reminder_id}"
                        initial_state = {
                            "messages": [HumanMessage(content=reminder_text)],
                            "skip_action_log": True,
                            "platform": "reminder",
                            "thread_id": thread_id,
                            "user_name": "Chinmay",
                            "user_id": thread_id,
                        }
                        token_ctx = None
                        try:
                            if target_chat_id:
                                token_ctx = set_current_chat_id(target_chat_id)
                            result = graph.invoke(
                                initial_state,
                                config={"configurable": {"thread_id": thread_id}}
                            )
                            ai_reply = _extract_last_ai_text(result)
                            outgoing_text = ai_reply or reminder_text
                            if telegram_token and target_chat_id:
                                send_message(telegram_token, target_chat_id, outgoing_text, None, False)
                            cur.execute(
                                "UPDATE reminders SET status='done' WHERE id=%s",
                                (reminder_id,),
                            )
                        except Exception as exc:
                            print(f"Error sending reminder {reminder_id}: {exc}")
                        finally:
                            if token_ctx is not None:
                                try:
                                    reset_current_chat_id(token_ctx)
                                except Exception:
                                    pass
        finally:
            conn.close()
        time.sleep(poll_interval)


def start_scheduler(
    poll_interval: int = POLL_INTERVAL,
    graph=None,
) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_scheduler,
        kwargs={"poll_interval": poll_interval, "graph": graph, "stop_event": stop_event},
        daemon=True,
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    run_scheduler()
