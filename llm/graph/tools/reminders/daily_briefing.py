import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import requests
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

from llm.graph.db import get_connection
from llm.graph.habits.action_log import get_recent_actions
from llm.graph.nodes.helpers import extract_text
from llm.services.time_manager import TimeManager
from llm.graph.tools.reminders.weakup_tools import set_current_chat_id, reset_current_chat_id

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


DEFAULT_POLL_INTERVAL = 60
DEFAULT_DAILY_TIME = "08:30"


def _should_enable_scheduler() -> bool:
    flag = os.getenv("DAILY_BRIEFING_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _should_use_agent_renderer() -> bool:
    flag = os.getenv("DAILY_BRIEFING_USE_AGENT", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _parse_daily_time(value: str) -> tuple[int, int]:
    raw = (value or DEFAULT_DAILY_TIME).strip()
    try:
        hh, mm = raw.split(":", 1)
        hour = int(hh)
        minute = int(mm)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except Exception:
        return 8, 30


def _get_timezone():
    tz_name = os.getenv("DAILY_BRIEFING_TIMEZONE", "").strip()
    if tz_name and ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            print(f"Invalid DAILY_BRIEFING_TIMEZONE '{tz_name}', using system local timezone.")
    return datetime.now().astimezone().tzinfo


def _extract_date_from_ts(ts: str, tzinfo) -> Optional[str]:
    if not ts:
        return None
    try:
        cleaned = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzinfo)
        return dt.astimezone(tzinfo).date().isoformat()
    except Exception:
        return None


def _extract_local_time_label(ts: str, tzinfo) -> Optional[str]:
    if not ts:
        return None
    try:
        cleaned = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzinfo)
        local = dt.astimezone(tzinfo)
        return local.strftime("%H:%M")
    except Exception:
        return None


def _weather_code_to_text(code: Optional[int]) -> str:
    mapping = {
        0: "clear",
        1: "mostly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "foggy",
        51: "light drizzle",
        53: "drizzle",
        55: "heavy drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "light showers",
        81: "showers",
        82: "heavy showers",
        95: "thunderstorm",
    }
    return mapping.get(code, "unknown")


def _fetch_weather(city: str, tzinfo) -> str:
    if not city:
        return "Weather unavailable (set DAILY_BRIEFING_CITY)."
    try:
        geo_resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=6,
        )
        geo_resp.raise_for_status()
        results = (geo_resp.json() or {}).get("results") or []
        if not results:
            return f"Weather unavailable (city not found: {city})."

        place = results[0]
        lat = place.get("latitude")
        lon = place.get("longitude")
        if lat is None or lon is None:
            return f"Weather unavailable (missing location coordinates for {city})."

        weather_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true",
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=8,
        )
        weather_resp.raise_for_status()
        payload = weather_resp.json() or {}
        current = payload.get("current_weather") or {}
        daily = payload.get("daily") or {}
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        codes = daily.get("weathercode") or []

        current_temp = current.get("temperature")
        high = highs[0] if highs else None
        low = lows[0] if lows else None
        code = current.get("weathercode")
        if code is None and codes:
            code = codes[0]
        summary = _weather_code_to_text(code)

        if current_temp is not None and high is not None and low is not None:
            return f"{city}: {current_temp}C now, high {high}C / low {low}C, {summary}."
        if high is not None and low is not None:
            return f"{city}: high {high}C / low {low}C, {summary}."
        return f"{city}: {summary}."
    except Exception as exc:
        return f"Weather unavailable ({exc})."


def _load_time_context(time_manager: Optional[TimeManager]) -> dict:
    if time_manager is None:
        return {}
    try:
        raw = time_manager.get_time_context()
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"Daily briefing time context error: {exc}")
        return {}


def _summarize_today_events(time_context: dict, local_today: str, tzinfo) -> list[str]:
    events = time_context.get("calendar_events") or []
    out = []
    for event in events:
        start_raw = (event or {}).get("start")
        summary = (event or {}).get("summary") or "Untitled"
        event_date = _extract_date_from_ts(start_raw, tzinfo)
        if event_date != local_today:
            continue
        time_label = _extract_local_time_label(start_raw, tzinfo)
        if time_label:
            out.append(f"{time_label} - {summary}")
        else:
            out.append(summary)
    return out[:6]


def _summarize_today_tasks(time_context: dict, local_today: str) -> list[str]:
    tasks = time_context.get("pending_tasks") or []
    due_today = []
    for task in tasks:
        content = (task or {}).get("content") or "Untitled task"
        due = (task or {}).get("due")
        priority = (task or {}).get("priority")
        if due == local_today:
            if priority is not None:
                due_today.append(f"{content} (p{priority})")
            else:
                due_today.append(content)
    if due_today:
        return due_today[:8]

    fallback = []
    for task in tasks[:5]:
        content = (task or {}).get("content") or "Untitled task"
        due = (task or {}).get("due") or "No date"
        fallback.append(f"{content} (due: {due})")
    return fallback


def _calculate_consecutive_days(dates: set, anchor) -> int:
    streak = 0
    probe = anchor
    while probe in dates:
        streak += 1
        probe = probe - timedelta(days=1)
    return streak


def _build_streak_status(chat_id: str, tzinfo) -> str:
    actions = get_recent_actions(thread_id=chat_id, since_hours=24 * 21, limit=500)
    if not actions:
        return "No action streak yet."

    dates = set()
    action_dates = {}
    for item in actions:
        ts = item.get("timestamp")
        action_type = (item.get("action_type") or "other").strip().lower()
        day_text = _extract_date_from_ts(ts or "", tzinfo)
        if not day_text:
            continue
        day = datetime.fromisoformat(day_text).date()
        dates.add(day)
        action_dates.setdefault(action_type, set()).add(day)

    if not dates:
        return "No action streak yet."

    today = datetime.now(tzinfo).date()
    yesterday = today - timedelta(days=1)
    anchor = today if today in dates else (yesterday if yesterday in dates else max(dates))
    active_streak = _calculate_consecutive_days(dates, anchor)

    best_type = None
    best_streak = 0
    for action_type, type_dates in action_dates.items():
        type_anchor = today if today in type_dates else (yesterday if yesterday in type_dates else max(type_dates))
        type_streak = _calculate_consecutive_days(type_dates, type_anchor)
        if type_streak > best_streak:
            best_streak = type_streak
            best_type = action_type

    if best_type and best_streak >= 2:
        return f"Active streak: {active_streak} days. Best streak: {best_type} for {best_streak} days."
    return f"Active streak: {active_streak} days."


def _build_nudge(chat_id: str, tzinfo) -> str:
    actions = get_recent_actions(thread_id=chat_id, since_hours=72, limit=200)
    if not actions:
        return "No strong recent pattern logged. Start with one focused 25-minute block this morning."

    commitments = [a for a in actions if a.get("commitment_made")]
    done_count = sum(1 for a in actions if str(a.get("status") or "").strip().lower() in {"done", "completed"})
    stressed = sum(1 for a in actions if str(a.get("sentiment") or "").strip().lower() in {"stressed", "anxious", "overwhelmed"})

    if commitments and done_count == 0:
        return "You made commitments recently but no clear completion logs. Close one open loop before noon."
    if stressed >= 2:
        return "Recent tone looks stressed. Protect 60 minutes of distraction-free work, then reassess."

    counts = {}
    for item in actions:
        action_type = (item.get("action_type") or "other").strip().lower()
        counts[action_type] = counts.get(action_type, 0) + 1
    top_action = max(counts, key=counts.get)
    return f"Pattern is consistent around '{top_action}'. Keep momentum by starting that first today."


def _load_pending_whatsapp(limit: int = 3) -> tuple[int, list[str]]:
    pending_path = Path(__file__).resolve().parents[4] / "integrations" / "whatsapp" / "pending.json"
    if not pending_path.exists():
        return 0, []
    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return 0, []
        pending = [p for p in data if isinstance(p, dict) and p.get("status") == "pending"]
        snippets = []
        for item in pending[:limit]:
            from_name = item.get("from_name") or item.get("from_id") or "Unknown"
            message = (item.get("message") or "").strip()
            if len(message) > 70:
                message = message[:67] + "..."
            snippets.append(f"{from_name}: {message}")
        return len(pending), snippets
    except Exception as exc:
        print(f"Daily briefing WhatsApp pending parse error: {exc}")
        return 0, []


def _build_raw_briefing(chat_id: str, time_manager: Optional[TimeManager], tzinfo, city: str) -> str:
    now_local = datetime.now(tzinfo)
    local_today = now_local.date().isoformat()
    time_context = _load_time_context(time_manager)

    events = _summarize_today_events(time_context, local_today, tzinfo)
    tasks = _summarize_today_tasks(time_context, local_today)
    weather = _fetch_weather(city, tzinfo)
    streak = _build_streak_status(chat_id, tzinfo)
    nudge = _build_nudge(chat_id, tzinfo)
    pending_count, pending_samples = _load_pending_whatsapp()

    lines = [
        f"Daily Briefing - {now_local.strftime('%A, %b %d')}",
        "",
        "Calendar today:",
    ]
    lines.extend([f"- {entry}" for entry in events] or ["- No events today."])

    lines.append("")
    lines.append("Tasks:")
    lines.extend([f"- {entry}" for entry in tasks] or ["- No pending tasks found."])

    lines.append("")
    lines.append("Weather:")
    lines.append(f"- {weather}")

    lines.append("")
    lines.append("Habit streak status:")
    lines.append(f"- {streak}")

    lines.append("")
    lines.append("WhatsApp pending:")
    lines.append(f"- {pending_count} pending")
    if pending_samples:
        lines.extend([f"- {sample}" for sample in pending_samples])

    lines.append("")
    lines.append("Nudge:")
    lines.append(f"- {nudge}")

    return "\n".join(lines)


def _extract_last_ai_text(result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not last_ai:
        return ""
    return extract_text(getattr(last_ai, "content", ""))


def _render_with_agent(graph, chat_id: str, raw_briefing: str) -> str:
    initial_state = {
        "messages": [
            HumanMessage(
                content=(
                    "Create a concise morning briefing for Chinmay using this data. "
                    "Keep it practical and include one direct call-out.\n\n"
                    f"{raw_briefing}"
                )
            )
        ],
        "skip_action_log": True,
        "platform": "daily_briefing",
        "thread_id": str(chat_id),
        "user_name": "Chinmay",
        "user_id": str(chat_id),
    }
    token_ctx = None
    try:
        token_ctx = set_current_chat_id(str(chat_id))
        result = graph.invoke(initial_state, config={"configurable": {"thread_id": str(chat_id)}})
        return _extract_last_ai_text(result)
    finally:
        if token_ctx is not None:
            try:
                reset_current_chat_id(token_ctx)
            except Exception:
                pass


def init_daily_briefing_db() -> None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS daily_briefing_runs (
                        chat_id TEXT NOT NULL,
                        run_date DATE NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (chat_id, run_date)
                    )
                    """
                )
    finally:
        conn.close()


def _claim_briefing_slot(chat_id: str, run_date) -> bool:
    """Atomically check-and-mark a briefing as claimed.

    Returns True if this caller won the slot (no prior row existed).
    Uses INSERT ... ON CONFLICT DO NOTHING to avoid race conditions
    when multiple processes check at the same time.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO daily_briefing_runs (chat_id, run_date, sent_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (chat_id, run_date) DO NOTHING
                    """,
                    (str(chat_id), run_date),
                )
                # rowcount == 1 means we inserted (won the slot)
                # rowcount == 0 means row already existed (another process got it)
                return cur.rowcount == 1
    finally:
        conn.close()


def run_daily_briefing_scheduler(
    poll_interval: int = DEFAULT_POLL_INTERVAL,
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
        print("Daily briefing scheduler disabled via DAILY_BRIEFING_ENABLE.")
        return

    token = os.getenv("TELEGRAM_API_TOKEN")
    chat_id = os.getenv("DAILY_BRIEFING_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Daily briefing disabled: TELEGRAM_API_TOKEN or target chat id missing.")
        return

    city = os.getenv("DAILY_BRIEFING_CITY", "").strip()
    daily_time = os.getenv("DAILY_BRIEFING_TIME", DEFAULT_DAILY_TIME)
    send_hour, send_minute = _parse_daily_time(daily_time)
    tzinfo = _get_timezone()
    use_agent = _should_use_agent_renderer()
    env_poll = os.getenv("DAILY_BRIEFING_POLL_INTERVAL")
    if env_poll:
        try:
            poll_interval = int(env_poll)
        except ValueError:
            print(f"Invalid DAILY_BRIEFING_POLL_INTERVAL '{env_poll}', using {poll_interval}")

    time_manager = None
    try:
        time_manager = TimeManager()
    except Exception as exc:
        print(f"Daily briefing TimeManager init failed, continuing with fallback data: {exc}")

    init_daily_briefing_db()

    while True:
        if stop_event and stop_event.is_set():
            print("Daily briefing scheduler stopping...")
            break

        now_local = datetime.now(tzinfo)
        run_date = now_local.date()
        is_due = (now_local.hour > send_hour) or (
            now_local.hour == send_hour and now_local.minute >= send_minute
        )

        if is_due and _claim_briefing_slot(str(chat_id), run_date):
            try:
                raw_brief = _build_raw_briefing(str(chat_id), time_manager, tzinfo, city)
                outgoing = raw_brief
                if graph is not None and use_agent:
                    ai_text = _render_with_agent(graph, str(chat_id), raw_brief)
                    if ai_text:
                        outgoing = ai_text
                send_message(token, str(chat_id), outgoing, None, False)
                print(f"Daily briefing sent for {run_date} to chat {chat_id}.")
            except Exception as exc:
                print(f"Failed to send daily briefing: {exc}")

        time.sleep(max(15, int(poll_interval)))


def start_daily_briefing_scheduler(
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    graph=None,
) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_daily_briefing_scheduler,
        kwargs={"poll_interval": poll_interval, "graph": graph, "stop_event": stop_event},
        daemon=True,
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    run_daily_briefing_scheduler()
