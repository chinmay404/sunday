"""
Proactive Engine — makes Sunday feel like a real person.

Uses EXISTING data only (no new API calls):
  - Calendar events from TimeManager (already cached)
  - last_seen tracking from action_log
  - Action logs / habit data

Triggers are pattern-based, not clock-based:
  1. Upcoming event awareness — notices events and decides whether to mention them
  2. Silence awareness — notices long gaps and decides whether to check in
  3. Commitment awareness — notices unfollowed commitments
  4. End-of-day awareness — if there was activity, maybe wrap up

The engine provides context to the LLM and lets IT decide what to say.
No rigid timings — just situation awareness.
"""

import json
import logging
import os
import random
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

DEFAULT_POLL_INTERVAL = 180  # check every 3 minutes
# Soft thresholds — hints, not hard rules
SILENCE_MIN_HOURS = float(os.getenv("PROACTIVE_SILENCE_HOURS", "5"))
EVENT_LOOKAHEAD_MINUTES = int(os.getenv("PROACTIVE_EVENT_LOOKAHEAD", "40"))
COMMITMENT_MIN_HOURS = float(os.getenv("PROACTIVE_COMMITMENT_HOURS", "3"))


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


def _count_today_sends(chat_id: str, today) -> int:
    """How many proactive messages have we sent today? Used to avoid spamming."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM proactive_sends WHERE chat_id = %s AND trigger_date = %s",
                    (str(chat_id), today),
                )
                return cur.fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


# ── Situation awareness (all cheap — DB/memory only) ─────────────────────

def _gather_situation(chat_id: str, tzinfo, time_manager) -> dict:
    """
    Gather all available context about what's going on right now.
    Returns a situation dict — the main loop decides what (if anything) to act on.
    """
    now = datetime.now(tzinfo)
    situation = {
        "now": now,
        "hour": now.hour,
        "is_waking_hours": 8 <= now.hour < 23,
        "is_evening": 20 <= now.hour < 23,
        "upcoming_events": [],
        "silence_hours": None,
        "last_seen_time": None,
        "open_commitments": [],
        "recent_actions": [],
        "had_activity_today": False,
        "reflection_impulses": [],
        "unresolved_threads": [],
        "world_model_vibe": {},
    }

    # ── Last seen ──
    last_seen = get_last_seen_time(chat_id)
    if last_seen:
        if last_seen.tzinfo is None:
            from datetime import timezone
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        last_local = last_seen.astimezone(tzinfo)
        situation["last_seen_time"] = last_local
        situation["silence_hours"] = (now - last_local).total_seconds() / 3600
        situation["had_activity_today"] = last_local.date() == now.date()

    # ── Recent actions ──
    actions = get_recent_actions(thread_id=chat_id, since_hours=12, limit=15)
    if actions:
        situation["recent_actions"] = actions
        if not situation["had_activity_today"]:
            situation["had_activity_today"] = True

        # Find open commitments
        situation["open_commitments"] = [
            a for a in actions
            if a.get("commitment_made")
            and str(a.get("status", "")).strip().lower() not in ("done", "completed", "cancelled")
        ]

    # ── Upcoming calendar events ──
    if time_manager:
        try:
            raw = time_manager.get_time_context()
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict):
                for ev in data.get("calendar_events", []):
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
                        diff_min = (start_local - now).total_seconds() / 60
                        if 0 < diff_min <= EVENT_LOOKAHEAD_MINUTES:
                            situation["upcoming_events"].append({
                                "summary": summary,
                                "start_local": start_local,
                                "minutes_until": int(diff_min),
                            })
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug("Proactive: calendar check failed: %s", exc)

    # ── Reflection impulses + world model (from night reflection) ──
    try:
        from llm.graph.memory.world_model import get_state
        impulses_entry = get_state("proactive_impulses")
        if impulses_entry and impulses_entry.get("value"):
            situation["reflection_impulses"] = impulses_entry["value"]

        threads_entry = get_state("unresolved_threads")
        if threads_entry and threads_entry.get("value"):
            situation["unresolved_threads"] = threads_entry["value"]

        # Grab a few world model keys for extra context
        for wm_key in ("current_mood", "energy_read", "working_on", "latest_pattern",
                        "current_opinion", "yesterday_digest", "tomorrow_awareness"):
            entry = get_state(wm_key)
            if entry and entry.get("value"):
                situation["world_model_vibe"][wm_key] = entry["value"]
    except Exception as exc:
        logger.debug("Proactive: world model read failed: %s", exc)

    return situation


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
        if ai_text and ai_text.strip().lower() != "skip":
            send_message(token, str(chat_id), ai_text, None, False)
            logger.info("🔔 [Proactive] Sent %s: %s", platform, ai_text[:120])
        elif ai_text:
            logger.info("🔕 [Proactive] LLM chose to skip %s", platform)
    except Exception as exc:
        logger.error("Proactive engine invoke failed (%s): %s", platform, exc)
    finally:
        if token_ctx is not None:
            try:
                reset_current_chat_id(token_ctx)
            except Exception:
                pass


# ── Main scheduler loop ───────────────────────────────────────────────────

MAX_DAILY_PROACTIVE = int(os.getenv("PROACTIVE_MAX_DAILY", "4"))

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

    logger.info("🧠 Proactive engine started (poll ~%ds)", poll_interval)

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Proactive engine stopping...")
            break

        today = datetime.now(tzinfo).date()

        try:
            # Don't spam — cap daily proactive messages
            sent_today = _count_today_sends(chat_id, today)
            if sent_today >= MAX_DAILY_PROACTIVE:
                time.sleep(poll_interval)
                continue

            situation = _gather_situation(chat_id, tzinfo, time_manager)
            now = situation["now"]

            # Skip outside waking hours
            if not situation["is_waking_hours"]:
                time.sleep(poll_interval)
                continue

            # ── 1. Upcoming event awareness ─────────────────────────
            for ev in situation["upcoming_events"]:
                trigger_key = f"event_{ev['summary'][:50]}"
                if _claim_trigger(chat_id, trigger_key, today):
                    context_bits = [
                        f"'{ev['summary']}' is coming up in about {ev['minutes_until']} minutes.",
                    ]
                    if situation["recent_actions"]:
                        recent = situation["recent_actions"][:3]
                        context_bits.append(
                            "Recent context: " + "; ".join(a.get("description", "") for a in recent)
                        )
                    msg = (
                        "You noticed Chinmay has something coming up. "
                        + " ".join(context_bits) + " "
                        "Decide if this is worth mentioning. If yes, be natural — "
                        "a quick heads-up, maybe a joke, maybe 'you ready?'. "
                        "If it's trivial, just respond with 'skip'."
                    )
                    _invoke_and_send(graph, chat_id, msg, platform="proactive_event")
                    time.sleep(3)

            # ── 2. Silence awareness ────────────────────────────────
            if (
                situation["silence_hours"] is not None
                and situation["silence_hours"] >= SILENCE_MIN_HOURS
                and situation["had_activity_today"]
            ):
                window_key = f"silence_{now.hour // 4}"
                if _claim_trigger(chat_id, window_key, today):
                    last_t = situation["last_seen_time"]
                    recent_context = ""
                    if situation["recent_actions"]:
                        items = [a.get("description", "") for a in situation["recent_actions"][:3]]
                        recent_context = f" Last things going on: {'; '.join(items)}."
                    msg = (
                        f"Chinmay's been quiet for about {int(situation['silence_hours'])} hours "
                        f"(last active ~{last_t.strftime('%H:%M') if last_t else 'earlier'}).{recent_context} "
                        "Decide whether to reach out. "
                        "Could be a quick 'hey', a tease, a question about something, "
                        "or just vibes. Don't be clinical. "
                        "If it doesn't make sense, respond with 'skip'."
                    )
                    _invoke_and_send(graph, chat_id, msg, platform="proactive_checkin")

            # ── 3. Commitment follow-up ─────────────────────────────
            if situation["open_commitments"]:
                oldest_commitment = None
                for c in situation["open_commitments"]:
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
                            hours_ago = (now - ct.astimezone(tzinfo)).total_seconds() / 3600
                            if hours_ago >= COMMITMENT_MIN_HOURS:
                                if oldest_commitment is None or hours_ago > oldest_commitment[1]:
                                    oldest_commitment = (c, hours_ago)
                        except Exception:
                            continue

                if oldest_commitment:
                    c, hours_ago = oldest_commitment
                    desc = c.get("description", "something")
                    if _claim_trigger(chat_id, f"commit_{desc[:40]}", today):
                        msg = (
                            f"Chinmay said he'd do: '{desc}' about {int(hours_ago)} hours ago. "
                            "No follow-up yet. Decide whether to nudge. "
                            "If yes, be natural — light nudge or a tease. "
                            "If it's not worth it, respond with 'skip'."
                        )
                        _invoke_and_send(graph, chat_id, msg, platform="proactive_followup")

            # ── 4. Evening awareness ────────────────────────────────
            if situation["is_evening"] and situation["had_activity_today"]:
                if _claim_trigger(chat_id, "evening", today):
                    action_bits = ""
                    if situation["recent_actions"]:
                        items = [f"{a['action_type']}: {a['description']}" for a in situation["recent_actions"][:5]]
                        action_bits = " Today's context: " + "; ".join(items)
                    msg = (
                        f"It's {now.strftime('%H:%M')}, evening. Chinmay was active today.{action_bits} "
                        "Decide whether to do a casual end-of-day thing. "
                        "Could be asking how his day went, referencing something specific, "
                        "or just dropping a vibe. Keep it light. "
                        "If it doesn't feel right, respond with 'skip'."
                    )
                    _invoke_and_send(graph, chat_id, msg, platform="proactive_evening")

            # ── 5. Reflection impulses (from night thinking) ────────
            impulses = situation.get("reflection_impulses", [])
            for impulse in impulses:
                if not isinstance(impulse, dict):
                    continue
                impulse_text = impulse.get("impulse", "")
                impulse_when = impulse.get("when", "whenever").lower()
                impulse_intensity = impulse.get("intensity", "medium").lower()
                impulse_reason = impulse.get("reason", "")

                # Match time of day roughly
                hour = now.hour
                time_match = (
                    impulse_when == "whenever"
                    or (impulse_when == "morning" and 8 <= hour < 12)
                    or (impulse_when == "afternoon" and 12 <= hour < 17)
                    or (impulse_when == "evening" and 17 <= hour < 23)
                )
                if not time_match:
                    continue

                trigger_key = f"impulse_{impulse_text[:40]}"
                if _claim_trigger(chat_id, trigger_key, today):
                    # Build rich context for the LLM
                    vibe_bits = ""
                    wm = situation.get("world_model_vibe", {})
                    if wm:
                        vibe_bits = " Your current read: " + "; ".join(
                            f"{k}={v}" for k, v in list(wm.items())[:4]
                        )
                    threads_bits = ""
                    threads = situation.get("unresolved_threads", [])
                    if threads:
                        threads_bits = f" Unresolved threads: {', '.join(str(t) for t in threads[:3])}."

                    msg = (
                        f"Last night while thinking, you had this impulse: '{impulse_text}'. "
                        f"Reason: {impulse_reason}. Intensity: {impulse_intensity}.{vibe_bits}{threads_bits} "
                        "Now it's daytime. Decide if this still feels right. "
                        "If yes, act on it naturally — text him like a real person would. "
                        "Be unpredictable. Don't be generic. "
                        "If it doesn't feel right anymore, respond with 'skip'."
                    )
                    _invoke_and_send(graph, chat_id, msg, platform="proactive_impulse")
                    time.sleep(3)
                    break  # max 1 impulse per cycle

        except Exception as exc:
            logger.error("Proactive engine cycle error: %s", exc)

        # Randomize interval so it doesn't feel mechanical
        jitter = random.randint(-30, 30)
        time.sleep(max(60, poll_interval + jitter))


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
