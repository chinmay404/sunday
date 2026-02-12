"""
Proactive Check-in Engine — makes Sunday feel like a real person.

Uses EXISTING data only (no new API calls):
  - Calendar events from TimeManager (already cached)
  - last_seen tracking from action_log
  - Pending reminders from DB
  - Action logs / habit data

Triggers (all auto-invoke the graph, send via Telegram):
  1. Pre-event nudge: 20-30 min before a calendar event
  2. Evening wrap-up: ~21:00 if there was morning activity
  3. Silence check-in: if Chinmay hasn't talked in 6+ hours during daytime
  4. Post-commitment follow-up: if a commitment was logged hours ago with no update

All checks are cheap DB/memory reads — only ONE LLM call happens when
we actually decide to send a message (via graph.invoke).
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage

from llm.graph.db import get_connection
from llm.graph.habits.action_log import (
    get_last_seen_time,
    get_recent_actions,
    list_thread_ids,
)
from llm.graph.nodes.helpers import extract_text
from llm.graph.tools.reminders.weakup_tools import set_current_chat_id, reset_current_chat_id

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# ── Config ─────────────────────────────────────────────────────────────────

DEFAULT_POLL_INTERVAL = 120  # check every 2 minutes
SILENCE_THRESHOLD_HOURS = float(os.getenv("PROACTIVE_SILENCE_HOURS", "6"))
EVENING_HOUR = int(os.getenv("PROACTIVE_EVENING_HOUR", "21"))
PRE_EVENT_MINUTES = int(os.getenv("PROACTIVE_PRE_EVENT_MINUTES", "25"))
COMMITMENT_FOLLOWUP_HOURS = float(os.getenv("PROACTIVE_COMMITMENT_HOURS", "4"))


def _should_enable() -> bool:
    flag = os.getenv("PROACTIVE_ENGINE_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _get_timezone():
    tz_name = os.getenv("DAILY_BRIEFING_TIMEZONE", "").strip()
    if tz_name and ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


# ── Atomic claim table (prevent duplicate sends) ──────────────────────────

def _init_proactive_db():
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS proactive_sends (
                        chat_id TEXT NOT NULL,
                        trigger_key TEXT NOT NULL,
                        trigger_date DATE NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (chat_id, trigger_key, trigger_date)
                    )
                """)
    finally:
        conn.close()


def _claim_trigger(chat_id: str, trigger_key: str, trigger_date) -> bool:
    """Atomically claim a trigger. Returns True if we won the slot."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO proactive_sends (chat_id, trigger_key, trigger_date)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (chat_id, trigger_key, trigger_date) DO NOTHING
                    """,
                    (str(chat_id), trigger_key, trigger_date),
                )
                return cur.rowcount == 1
    finally:
        conn.close()


# ── Trigger checks (all cheap — DB/memory only) ──────────────────────────

def _get_upcoming_events(time_manager, tzinfo, within_minutes: int = 35) -> List[dict]:
    """Get calendar events happening in the next N minutes. Uses cached TimeManager."""
    if not time_manager:
        return []
    try:
        raw = time_manager.get_time_context()
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            return []
        events = data.get("calendar_events", [])
        now = datetime.now(tzinfo)
        upcoming = []
        for ev in events:
            start_raw = (ev or {}).get("start")
            summary = (ev or {}).get("summary", "Untitled")
            if not start_raw:
                continue
            try:
                cleaned = start_raw.replace("Z", "+00:00")
                start_dt = datetime.fromisoformat(cleaned)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=tzinfo)
                start_local = start_dt.astimezone(tzinfo)
                diff = (start_local - now).total_seconds() / 60
                if 0 < diff <= within_minutes:
                    upcoming.append({
                        "summary": summary,
                        "start_local": start_local,
                        "minutes_until": int(diff),
                    })
            except Exception:
                continue
        return upcoming
    except Exception as exc:
        logger.debug("Proactive engine: calendar check failed: %s", exc)
        return []


def _check_silence(chat_id: str, tzinfo) -> Optional[str]:
    """Check if Chinmay has been silent for too long during daytime hours."""
    now = datetime.now(tzinfo)
    hour = now.hour
    
    # Only check during waking hours (8am - 11pm)
    if hour < 8 or hour >= 23:
        return None

    last_seen = get_last_seen_time(chat_id)
    if not last_seen:
        return None

    if last_seen.tzinfo is None:
        from datetime import timezone
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    
    last_seen_local = last_seen.astimezone(tzinfo)
    silence_hours = (now - last_seen_local).total_seconds() / 3600

    if silence_hours >= SILENCE_THRESHOLD_HOURS:
        # Check it's not just overnight silence
        if last_seen_local.date() == now.date() or (
            last_seen_local.date() == (now - timedelta(days=1)).date() and last_seen_local.hour >= 20
        ):
            return (
                f"Chinmay hasn't said anything in about {int(silence_hours)} hours. "
                f"Last active around {last_seen_local.strftime('%H:%M')}. "
                f"It's now {now.strftime('%H:%M')}. "
                "Check in naturally — don't mention tracking silence. "
                "Reference whatever was last discussed or what's on his schedule."
            )
    return None


def _check_unfollowed_commitments(chat_id: str, tzinfo) -> Optional[str]:
    """Check if there are recent commitments with no follow-up."""
    now = datetime.now(tzinfo)
    hour = now.hour
    if hour < 9 or hour >= 22:
        return None

    actions = get_recent_actions(
        thread_id=chat_id,
        since_hours=COMMITMENT_FOLLOWUP_HOURS * 2,
        limit=20,
    )
    if not actions:
        return None

    commitments = [
        a for a in actions
        if a.get("commitment_made")
        and str(a.get("status", "")).strip().lower() not in ("done", "completed", "cancelled")
    ]
    if not commitments:
        return None

    # Check if there's been any activity AFTER the commitment
    latest_commitment_ts = None
    for c in commitments:
        ts_str = c.get("timestamp")
        if ts_str:
            try:
                cleaned = ts_str if isinstance(ts_str, str) else str(ts_str)
                if cleaned.endswith("Z"):
                    cleaned = cleaned[:-1] + "+00:00"
                ct = datetime.fromisoformat(cleaned)
                if ct.tzinfo is None:
                    from datetime import timezone as tz
                    ct = ct.replace(tzinfo=tz.utc)
                if latest_commitment_ts is None or ct > latest_commitment_ts:
                    latest_commitment_ts = ct
            except Exception:
                continue

    if latest_commitment_ts:
        hours_since = (datetime.now(tzinfo) - latest_commitment_ts.astimezone(tzinfo)).total_seconds() / 3600
        if hours_since >= COMMITMENT_FOLLOWUP_HOURS:
            descriptions = [c.get("description", "something") for c in commitments[:2]]
            return (
                f"Chinmay committed to: {', '.join(descriptions)} "
                f"about {int(hours_since)} hours ago but hasn't followed up. "
                "Ask how it went naturally — don't sound like a tracker."
            )
    return None


def _should_evening_wrapup(chat_id: str, tzinfo) -> Optional[str]:
    """Check if it's time for an evening wrap-up."""
    now = datetime.now(tzinfo)
    if now.hour != EVENING_HOUR:
        return None

    # Only wrap up if there was meaningful activity today
    actions_today = get_recent_actions(thread_id=chat_id, since_hours=14, limit=10)
    last_seen = get_last_seen_time(chat_id)

    had_activity = bool(actions_today) or (
        last_seen and last_seen.astimezone(tzinfo).date() == now.date()
    )

    if not had_activity:
        return None

    action_summary = ""
    if actions_today:
        items = [f"- {a['action_type']}: {a['description']}" for a in actions_today[:5]]
        action_summary = "\nToday's logged actions:\n" + "\n".join(items)

    return (
        "It's evening. Time for a casual end-of-day check-in with Chinmay. "
        "Don't be formal — just a quick 'how'd today go' vibe. "
        "Reference what you know about his day. "
        "If he had events or commitments, ask about them. "
        "If he seems to have had a quiet day, acknowledge that. "
        f"Keep it to 2-3 sentences max.{action_summary}"
    )


# ── Graph invocation ──────────────────────────────────────────────────────

def _extract_last_ai_text(result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not last_ai:
        return ""
    return extract_text(getattr(last_ai, "content", ""))


def _invoke_and_send(graph, chat_id: str, trigger_message: str, platform: str = "proactive"):
    """Invoke the graph with a trigger and send the response via Telegram."""
    from integrations.telegram.send_telegram import send_message

    token = os.getenv("TELEGRAM_API_TOKEN")
    if not token:
        return

    initial_state = {
        "messages": [HumanMessage(content=trigger_message)],
        "skip_action_log": True,
        "platform": platform,
        "thread_id": str(chat_id),
        "user_name": "Chinmay",
        "user_id": str(chat_id),
    }
    token_ctx = None
    try:
        token_ctx = set_current_chat_id(str(chat_id))
        result = graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": str(chat_id)}},
        )
        ai_text = _extract_last_ai_text(result)
        if ai_text:
            send_message(token, str(chat_id), ai_text, None, False)
            logger.info("🔔 [Proactive] Sent %s to %s: %s", platform, chat_id, ai_text[:100])
    except Exception as exc:
        logger.error("Proactive engine invoke failed (%s): %s", platform, exc)
    finally:
        if token_ctx is not None:
            try:
                reset_current_chat_id(token_ctx)
            except Exception:
                pass


# ── Main scheduler loop ───────────────────────────────────────────────────

def run_proactive_engine(
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    graph=None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    load_dotenv(root_dir / ".env")
    if not _should_enable():
        logger.info("Proactive engine disabled via PROACTIVE_ENGINE_ENABLE.")
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.warning("Proactive engine: no TELEGRAM_CHAT_ID, disabled.")
        return

    tzinfo = _get_timezone()

    # TimeManager for calendar checks (reuses cached data, no extra API calls)
    time_manager = None
    try:
        from llm.services.time_manager import TimeManager
        time_manager = TimeManager()
    except Exception as exc:
        logger.warning("Proactive engine: TimeManager unavailable: %s", exc)

    _init_proactive_db()

    if graph is None:
        from llm.graph.graph import create_graph
        graph = create_graph()

    logger.info("🧠 Proactive engine started (poll every %ds)", poll_interval)

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Proactive engine stopping...")
            break

        now = datetime.now(tzinfo)
        today = now.date()

        try:
            # ── 1. Pre-event nudges ──────────────────────────────────
            upcoming = _get_upcoming_events(time_manager, tzinfo, within_minutes=PRE_EVENT_MINUTES)
            for ev in upcoming:
                trigger_key = f"pre_event_{ev['summary'][:50]}"
                if _claim_trigger(chat_id, trigger_key, today):
                    msg = (
                        f"Calendar event '{ev['summary']}' starts in {ev['minutes_until']} minutes. "
                        "Give Chinmay a heads-up. Be brief and natural — "
                        "like a friend reminding him. If you know context about this event, reference it."
                    )
                    _invoke_and_send(graph, chat_id, msg, platform="proactive_event")
                    time.sleep(2)  # small gap between sends

            # ── 2. Silence check-in ──────────────────────────────────
            silence_msg = _check_silence(chat_id, tzinfo)
            if silence_msg:
                # Only one silence check per 6-hour window
                window_key = f"silence_{now.hour // 6}"
                if _claim_trigger(chat_id, window_key, today):
                    _invoke_and_send(graph, chat_id, silence_msg, platform="proactive_checkin")

            # ── 3. Commitment follow-up ──────────────────────────────
            commit_msg = _check_unfollowed_commitments(chat_id, tzinfo)
            if commit_msg:
                if _claim_trigger(chat_id, "commitment_followup", today):
                    _invoke_and_send(graph, chat_id, commit_msg, platform="proactive_followup")

            # ── 4. Evening wrap-up ───────────────────────────────────
            evening_msg = _should_evening_wrapup(chat_id, tzinfo)
            if evening_msg:
                if _claim_trigger(chat_id, "evening_wrapup", today):
                    _invoke_and_send(graph, chat_id, evening_msg, platform="proactive_evening")

        except Exception as exc:
            logger.error("Proactive engine cycle error: %s", exc)

        time.sleep(max(30, poll_interval))


def start_proactive_engine(
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    graph=None,
) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_proactive_engine,
        kwargs={"poll_interval": poll_interval, "graph": graph, "stop_event": stop_event},
        daemon=True,
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    run_proactive_engine()
