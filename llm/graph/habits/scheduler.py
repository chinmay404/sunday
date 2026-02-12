import os
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv

DEFAULT_POLL_INTERVAL = 300
DEFAULT_INACTIVITY_HOURS = 3.0
DEFAULT_LOOKBACK_HOURS = float(24 * 7)


def _should_enable_scheduler() -> bool:
    flag = os.getenv("HABIT_ANALYZER_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _should_notify() -> bool:
    flag = os.getenv("HABIT_NOTIFY_TELEGRAM", "false").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _build_notification(result) -> str:
    missed = ", ".join(result.missed_actions) if result.missed_actions else "None"
    reminder = result.high_priority_reminder or "None"
    return (
        "Habit Analyzer Update\n"
        f"Updated Profile: {result.updated_habit_profile}\n"
        f"Habit Shift: {result.habit_shift}\n"
        f"Missed Actions: {missed}\n"
        f"High Priority Reminder: {reminder}"
    )


def run_habit_scheduler(
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    stop_event: Optional[threading.Event] = None,
) -> None:
    # Ensure project root is on sys.path for absolute imports if run as script
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    load_dotenv(root_dir / ".env")
    env_poll = os.getenv("HABIT_POLL_INTERVAL")
    if env_poll:
        try:
            poll_interval = int(env_poll)
        except ValueError:
            print(f"Invalid HABIT_POLL_INTERVAL '{env_poll}', using {poll_interval}")
    env_inactivity = os.getenv("HABIT_INACTIVITY_HOURS")
    inactivity_hours = DEFAULT_INACTIVITY_HOURS
    if env_inactivity:
        try:
            inactivity_hours = float(env_inactivity)
        except ValueError:
            print(f"Invalid HABIT_INACTIVITY_HOURS '{env_inactivity}', using {inactivity_hours}")
    env_lookback = os.getenv("HABIT_LOOKBACK_HOURS")
    lookback_hours = DEFAULT_LOOKBACK_HOURS
    if env_lookback:
        try:
            lookback_hours = float(env_lookback)
        except ValueError:
            print(f"Invalid HABIT_LOOKBACK_HOURS '{env_lookback}', using {lookback_hours}")
    from llm.graph.habits.action_log import (
        list_thread_ids,
        get_last_action_time,
        get_last_seen_time,
        get_last_synthesis_run,
    )
    from llm.graph.habits.synthesis import run_habit_synthesis
    if not _should_enable_scheduler():
        print("Habit analyzer disabled via HABIT_ANALYZER_ENABLE.")
        return

    # Run episodic memory cleanup once at startup, then daily
    _last_cleanup = [0.0]  # mutable container for closure
    CLEANUP_INTERVAL = 86400  # 24 hours

    def _maybe_cleanup_memories():
        now_ts = time.time()
        if now_ts - _last_cleanup[0] >= CLEANUP_INTERVAL:
            try:
                from llm.graph.memory.episodic_memeory import EpisodicMemory
                em = EpisodicMemory()
                deleted = em.cleanup_memories(threshold=0.05)
                if deleted:
                    print(f"🧹 Episodic cleanup: removed {deleted} decayed/expired memories")
                _last_cleanup[0] = now_ts
            except Exception as exc:
                print(f"Episodic cleanup error: {exc}")

    notify = _should_notify()
    telegram_token = os.getenv("TELEGRAM_API_TOKEN") if notify else None
    default_chat_id = os.getenv("TELEGRAM_CHAT_ID") if notify else None

    while True:
        if stop_event and stop_event.is_set():
            print("Habit analyzer stopping...")
            break

        _maybe_cleanup_memories()

        now = datetime.now(timezone.utc)
        inactivity_delta = timedelta(hours=inactivity_hours)

        for thread_id in list_thread_ids():
            last_seen = get_last_seen_time(thread_id)
            if not last_seen:
                continue
            if now - last_seen < inactivity_delta:
                continue

            last_action = get_last_action_time(thread_id)
            if not last_action:
                continue

            last_run = get_last_synthesis_run(thread_id)
            if last_run and last_run >= last_seen:
                continue

            result = run_habit_synthesis(
                thread_id=thread_id,
                lookback_hours=lookback_hours,
            )
            if not result:
                continue

            print(f"Habit synthesis completed for thread {thread_id}")

            if notify and telegram_token and default_chat_id:
                try:
                    from integrations.telegram.send_telegram import send_message

                    message = _build_notification(result)
                    send_message(telegram_token, default_chat_id, message, None, False)
                except Exception as exc:
                    print(f"Failed to send habit notification: {exc}")

        time.sleep(poll_interval)


def start_habit_scheduler(
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_habit_scheduler,
        kwargs={"poll_interval": poll_interval, "stop_event": stop_event},
        daemon=True,
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    run_habit_scheduler()
