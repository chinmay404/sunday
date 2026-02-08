import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

from llm.services.location_service import (
    LocationService,
    set_current_location_user_id,
    reset_current_location_user_id,
)
from llm.graph.tools.reminders.weakup_tools import (
    set_current_chat_id,
    reset_current_chat_id,
)


DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_SCAN_INTERVAL_MINUTES = 30.0
DEFAULT_PATTERN_COOLDOWN_HOURS = 8.0
DEFAULT_PATTERN_MAX_AGE_HOURS = 6.0


def _should_enable_scheduler() -> bool:
    flag = os.getenv("LOCATION_OBSERVER_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _scan_interval_minutes() -> float:
    raw = os.getenv("LOCATION_OBSERVER_INTERVAL_MINUTES", str(DEFAULT_SCAN_INTERVAL_MINUTES)).strip()
    try:
        return max(5.0, float(raw))
    except Exception:
        return DEFAULT_SCAN_INTERVAL_MINUTES


def _cooldown_hours() -> float:
    raw = os.getenv("LOCATION_OBSERVER_COOLDOWN_HOURS", str(DEFAULT_PATTERN_COOLDOWN_HOURS)).strip()
    try:
        return max(1.0, float(raw))
    except Exception:
        return DEFAULT_PATTERN_COOLDOWN_HOURS


def _max_age_hours() -> float:
    raw = os.getenv("LOCATION_OBSERVER_MAX_AGE_HOURS", str(DEFAULT_PATTERN_MAX_AGE_HOURS)).strip()
    try:
        return max(1.0, float(raw))
    except Exception:
        return DEFAULT_PATTERN_MAX_AGE_HOURS


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


def _build_observer_event(analysis: dict) -> str:
    lat = analysis.get("latitude")
    lon = analysis.get("longitude")
    dwell = int(float(analysis.get("dwell_minutes", 0)))
    summary = analysis.get("summary", "Pattern detected.")
    return (
        "Location observer trigger.\n"
        f"Summary: {summary}\n"
        f"Current coordinates: lat={lat}, lon={lon}\n"
        f"Dwell time here: {dwell} minutes\n"
        "Ask Chinmay a short, natural check-in question. "
        "If appropriate, ask if this location should be remembered (for example home/office/gym)."
    )


def run_location_observer_scheduler(
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    graph=None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from integrations.telegram.send_telegram import send_message

    load_dotenv(root_dir / ".env")
    if not _should_enable_scheduler():
        print("Location observer disabled via LOCATION_OBSERVER_ENABLE.")
        return

    token = os.getenv("TELEGRAM_API_TOKEN")
    default_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token and not graph:
        print("Location observer skipped: TELEGRAM_API_TOKEN missing and graph unavailable.")
        return

    if graph is None:
        from llm.graph.graph import create_graph
        graph = create_graph()

    location_service = LocationService()
    next_scan_at = 0.0

    while True:
        if stop_event and stop_event.is_set():
            print("Location observer stopping...")
            break

        now = time.time()
        if now < next_scan_at:
            time.sleep(max(1, int(poll_interval_seconds)))
            continue
        next_scan_at = now + (_scan_interval_minutes() * 60.0)

        for user_id in location_service.list_tracked_users():
            decision = location_service.should_prompt_about_pattern(
                user_id=user_id,
                cooldown_hours=_cooldown_hours(),
                max_age_hours=_max_age_hours(),
            )
            if not decision:
                continue

            chat_id = (
                location_service.get_chat_id_for_user(user_id)
                or default_chat_id
                or str(user_id)
            )
            event_text = _build_observer_event(decision)
            outgoing_text = event_text

            chat_ctx = None
            user_ctx = None
            try:
                if graph is not None:
                    chat_ctx = set_current_chat_id(str(chat_id))
                    user_ctx = set_current_location_user_id(str(user_id))
                    result = graph.invoke(
                        {
                            "messages": [HumanMessage(content=event_text)],
                            "skip_action_log": True,
                            "platform": "location_observer",
                            "thread_id": str(chat_id),
                            "user_name": "Chinmay",
                            "user_id": str(user_id),
                        },
                        config={"configurable": {"thread_id": str(chat_id)}},
                    )
                    ai_text = _extract_last_ai_text(result)
                    if ai_text:
                        outgoing_text = ai_text

                if token and chat_id:
                    send_message(token, str(chat_id), outgoing_text, None, False)
                    location_service.mark_pattern_prompt_sent(
                        user_id=user_id,
                        reason_key=str(decision.get("reason_key", "unknown")),
                    )
            except Exception as exc:
                print(f"Location observer send failed for user {user_id}: {exc}")
            finally:
                if chat_ctx is not None:
                    try:
                        reset_current_chat_id(chat_ctx)
                    except Exception:
                        pass
                if user_ctx is not None:
                    try:
                        reset_current_location_user_id(user_ctx)
                    except Exception:
                        pass

        time.sleep(max(1, int(poll_interval_seconds)))


def start_location_observer_scheduler(
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    graph=None,
) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_location_observer_scheduler,
        kwargs={
            "poll_interval_seconds": poll_interval_seconds,
            "graph": graph,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    run_location_observer_scheduler()
