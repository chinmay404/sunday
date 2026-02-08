import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from llm.services.location_service import (
    LocationService,
    _haversine_meters,
)


DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_SCAN_INTERVAL_MINUTES = 30.0
DEFAULT_COOLDOWN_HOURS = 2.0
DEFAULT_MAX_LOCATION_AGE_HOURS = 2.0
DEFAULT_HOME_EXTENDED_HOURS = 18.0
DEFAULT_UNKNOWN_DWELL_MINUTES = 30.0


# ---------------------------------------------------------------------------
# Weather code mapping (shared with daily_briefing)
# ---------------------------------------------------------------------------

_WEATHER_CODE_MAP = {
    0: "clear sky",
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


def _fetch_weather_by_coords(lat: float, lon: float) -> Optional[Dict]:
    """Fetch current weather from Open-Meteo using coordinates. No API key needed."""
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true",
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        current = payload.get("current_weather") or {}
        daily = payload.get("daily") or {}
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        codes = daily.get("weathercode") or []

        temp_now = current.get("temperature")
        wind_speed = current.get("windspeed")
        code = current.get("weathercode")
        if code is None and codes:
            code = codes[0]
        high = highs[0] if highs else None
        low = lows[0] if lows else None
        condition = _WEATHER_CODE_MAP.get(code, "unknown")

        return {
            "temp_now": temp_now,
            "high": high,
            "low": low,
            "wind_speed": wind_speed,
            "condition": condition,
            "code": code,
        }
    except Exception as exc:
        print(f"Location observer weather fetch failed: {exc}")
        return None


def _weather_to_report_line(weather: Optional[Dict]) -> str:
    if not weather:
        return "Weather: unavailable"
    temp = weather.get("temp_now")
    high = weather.get("high")
    low = weather.get("low")
    condition = weather.get("condition", "unknown")
    wind = weather.get("wind_speed")
    parts = [f"Weather: {condition}"]
    if temp is not None:
        parts.append(f"{temp}°C now")
    if high is not None and low is not None:
        parts.append(f"high {high}°C / low {low}°C")
    if wind is not None and wind > 30:
        parts.append(f"wind {wind} km/h (strong)")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

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
    raw = os.getenv("LOCATION_OBSERVER_COOLDOWN_HOURS", str(DEFAULT_COOLDOWN_HOURS)).strip()
    try:
        return max(0.5, float(raw))
    except Exception:
        return DEFAULT_COOLDOWN_HOURS


def _max_age_hours() -> float:
    raw = os.getenv("LOCATION_OBSERVER_MAX_AGE_HOURS", str(DEFAULT_MAX_LOCATION_AGE_HOURS)).strip()
    try:
        return max(0.5, float(raw))
    except Exception:
        return DEFAULT_MAX_LOCATION_AGE_HOURS


# ---------------------------------------------------------------------------
# Structured output for the ONE LLM call
# ---------------------------------------------------------------------------

class LocationCheckDecision(BaseModel):
    should_message: bool = Field(description="True ONLY if Sunday should send a message right now")
    message: str = Field(default="", description="The short, natural message to send (1-2 lines max)")
    reason: str = Field(description="Internal reasoning for the decision (not shown to user)")


# ---------------------------------------------------------------------------
# In-memory cooldown (resets on restart, which is fine)
# ---------------------------------------------------------------------------

_last_message_time: Dict[str, float] = {}


def _in_cooldown(user_id: str) -> bool:
    last = _last_message_time.get(user_id, 0)
    return (time.time() - last) < (_cooldown_hours() * 3600)


def _mark_messaged(user_id: str) -> None:
    _last_message_time[user_id] = time.time()


# ---------------------------------------------------------------------------
# Situation report builder (NO LLM call — pure data analysis + 1 weather API)
# ---------------------------------------------------------------------------

def _build_situation_report(location_service: LocationService, user_id: str) -> Optional[Dict]:
    """
    Gather all location intelligence for one user into a human-readable report.
    This is cheap — local data + one optional geocode + one free weather API call.
    """
    max_age = _max_age_hours()
    loc = location_service.get_location(user_id, max_age_hours=max_age)
    if not loc:
        return None

    lat = float(loc["latitude"])
    lon = float(loc["longitude"])
    age_minutes = max(0, (time.time() - float(loc["timestamp"])) / 60)

    # Lazy-resolve address if not cached yet (one geocode call, cached for future)
    address = str(loc.get("address_short", "")).strip()
    if not address:
        try:
            addr_info = location_service._resolve_address_for_coordinates(lat, lon)
            if addr_info:
                address = str(addr_info.get("short", "")).strip()
        except Exception:
            pass
    address = address or "unknown area"

    # Current saved place?
    place = location_service.resolve_current_place(user_id, max_age_hours=max_age)
    place_name = place["label"] if place else None

    # Short-term dwell (last 6h)
    pattern = location_service.analyze_pattern(user_id, max_age_hours=6)
    dwell_minutes = pattern.get("dwell_minutes", 0) if pattern.get("available") else 0

    # Movement in last hour
    history_1h = location_service.get_history(user_id, lookback_hours=1)
    distance_1h = 0.0
    if len(history_1h) >= 2:
        for i in range(1, len(history_1h)):
            distance_1h += _haversine_meters(
                float(history_1h[i - 1]["latitude"]),
                float(history_1h[i - 1]["longitude"]),
                float(history_1h[i]["latitude"]),
                float(history_1h[i]["longitude"]),
            )

    # Weather (free Open-Meteo API, no key needed)
    weather = _fetch_weather_by_coords(lat, lon)

    # Extended home-stay detection
    extended_home_hours = None
    home_threshold = float(os.getenv("LOCATION_HOME_EXTENDED_HOURS", str(DEFAULT_HOME_EXTENDED_HOURS)))
    if place_name and place_name.lower() == "home":
        saved_places = location_service.list_places(user_id)
        home_place = next((p for p in saved_places if p["label"].lower() == "home"), None)
        if home_place:
            # Check if ALL history points in the last 48h are within home radius
            history_long = location_service.get_history(user_id, lookback_hours=48)
            if len(history_long) >= 10:  # Need enough data points to be confident
                home_radius = float(home_place.get("radius_m", 250))
                all_home = all(
                    _haversine_meters(
                        float(p["latitude"]),
                        float(p["longitude"]),
                        float(home_place["latitude"]),
                        float(home_place["longitude"]),
                    )
                    <= home_radius
                    for p in history_long
                )
                if all_home:
                    first_ts = float(history_long[0]["timestamp"])
                    extended_home_hours = (time.time() - first_ts) / 3600

    # Saved places
    saved_places = location_service.list_places(user_id)
    place_labels = [p["label"] for p in saved_places]

    # ------------------------------------------------------------------
    # Build human-readable report
    # ------------------------------------------------------------------
    lines = []
    lines.append(f"Location data freshness: {int(age_minutes)} minutes old")

    if place_name:
        lines.append(f"Currently at: saved place '{place_name}' ({address})")
    else:
        lines.append(f"Currently at: unsaved/unknown location ({address})")

    lines.append(f"Time in current area: ~{int(dwell_minutes)} minutes")

    # Weather line
    lines.append(_weather_to_report_line(weather))

    if extended_home_hours is not None and extended_home_hours >= home_threshold:
        lines.append(
            f"Extended home stay: user has not left home in ~{int(extended_home_hours)} hours "
            f"(based on {len(location_service.get_history(user_id, lookback_hours=48))} tracking points)"
        )

    if distance_1h > 500:
        lines.append(f"Movement in last hour: {int(distance_1h)}m — actively traveling")
    elif distance_1h > 100:
        lines.append(f"Movement in last hour: {int(distance_1h)}m — some movement")
    else:
        lines.append("Movement in last hour: minimal — stationary")

    if place_labels:
        lines.append(f"Saved places: {', '.join(place_labels)}")
    else:
        lines.append("No saved places yet.")

    return {
        "report": "\n".join(lines),
        "user_id": user_id,
        "chat_id": str(loc.get("chat_id", user_id)),
        "place_name": place_name,
        "dwell_minutes": dwell_minutes,
        "distance_1h": distance_1h,
        "extended_home_hours": extended_home_hours,
        "address": address,
        "weather": weather,
    }


# ---------------------------------------------------------------------------
# ONE cheap LLM call — structured output, no tools, no graph
# ---------------------------------------------------------------------------

def _make_decision(situation_report: str) -> Optional[LocationCheckDecision]:
    try:
        from llm.graph.model.llm import get_llm
        from langchain_core.messages import SystemMessage
    except Exception:
        return None

    llm = get_llm(temperature=0.3)
    if not llm:
        return None

    now = datetime.now().astimezone()
    now_str = now.strftime("%A %H:%M")
    hour = now.hour

    prompt = (
        "You are Sunday, Chinmay's personal AI assistant and close friend. "
        "You just did a background location + weather check. Based on the situation below, "
        "decide whether to send Chinmay a short Telegram message.\n\n"
        "SCENARIOS WHERE YOU SHOULD MESSAGE:\n"
        "- At an unknown/unsaved place for 30+ minutes → casually ask what's up, offer to save it\n"
        "- At home for 18+ hours straight → gentle nudge, check if he's alright (don't nag)\n"
        "- Actively moving/traveling at an unusual time → quick check-in\n"
        "- Left home very late at night → \"heading somewhere?\"\n"
        "- Heavy rain/snow/thunderstorm AND user is outside or traveling → heads up about weather\n"
        "- Freezing temp (<0°C) AND user is outside → quick weather warning\n"
        "- Extreme heat (>35°C) AND user is outside → remind to stay hydrated\n\n"
        "SCENARIOS WHERE YOU SHOULD STAY SILENT:\n"
        "- At a known/saved place doing normal stuff with normal weather\n"
        "- Stationary at home during normal hours (under 18h)\n"
        "- Between midnight and 7am UNLESS something seems genuinely off\n"
        "- If nothing is interesting or actionable\n"
        "- Mild/normal weather when user is indoors — don't mention weather\n\n"
        "TONE RULES:\n"
        "- Talk like a close friend, not a robot or assistant\n"
        "- One or two short lines max\n"
        "- You can be casual, sarcastic, or caring depending on context\n"
        "- Never say \"I noticed your location\" or sound surveillance-y\n"
        "- Weather mentions should be natural: \"it's pouring outside btw\" not \"Weather alert: rain detected\"\n"
        "- Never be annoying. When in doubt, stay silent.\n\n"
        f"CURRENT TIME: {now_str} (hour={hour})\n\n"
        f"SITUATION:\n{situation_report}"
    )

    try:
        structured_llm = llm.with_structured_output(LocationCheckDecision)
        return structured_llm.invoke([SystemMessage(content=prompt)])
    except Exception as exc:
        print(f"Location observer LLM error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Telegram sender
# ---------------------------------------------------------------------------

def _send_telegram(token: str, chat_id: str, message: str) -> bool:
    try:
        from integrations.telegram.send_telegram import send_message
        send_message(token=token, chat_id=chat_id, message=message, parse_mode=None, disable_preview=True)
        return True
    except Exception as exc:
        print(f"Location observer Telegram send failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main scheduler loop
# ---------------------------------------------------------------------------

def run_location_observer_scheduler(
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    graph=None,  # kept for backwards compatibility with api.py, not used
    stop_event: Optional[threading.Event] = None,
) -> None:
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    load_dotenv(root_dir / ".env")
    if not _should_enable_scheduler():
        print("Location observer disabled via LOCATION_OBSERVER_ENABLE.")
        return

    token = os.getenv("TELEGRAM_API_TOKEN")
    if not token:
        print("Location observer skipped: TELEGRAM_API_TOKEN missing.")
        return

    location_service = LocationService()
    next_scan_at = time.time() + 60  # Wait 1 minute after startup before first scan

    print(f"📍 Location observer started (scan every {_scan_interval_minutes()} min, cooldown {_cooldown_hours()}h)")

    while True:
        if stop_event and stop_event.is_set():
            print("Location observer stopping...")
            break

        now = time.time()
        if now < next_scan_at:
            time.sleep(min(poll_interval_seconds, max(1, int(next_scan_at - now))))
            continue

        next_scan_at = now + (_scan_interval_minutes() * 60.0)

        for user_id in location_service.list_tracked_users():
            if _in_cooldown(user_id):
                continue

            try:
                situation = _build_situation_report(location_service, user_id)
                if not situation:
                    continue

                print(f"📍 Location scan for {user_id}:\n{situation['report']}")

                decision = _make_decision(situation["report"])
                if not decision:
                    continue

                if not decision.should_message:
                    print(f"📍 Decision: stay silent ({decision.reason})")
                    continue

                message = (decision.message or "").strip()
                if not message:
                    continue

                chat_id = situation["chat_id"]
                print(f"📍 Decision: message → {chat_id}: {message} ({decision.reason})")

                if _send_telegram(token, str(chat_id), message):
                    _mark_messaged(user_id)
                    # Also mark in persistent storage so it survives restarts
                    try:
                        location_service.mark_pattern_prompt_sent(
                            user_id=user_id,
                            reason_key=decision.reason[:100],
                        )
                    except Exception:
                        pass

            except Exception as exc:
                print(f"Location observer error for user {user_id}: {exc}")

        # Sleep in small chunks so stop_event is responsive
        time.sleep(max(1, poll_interval_seconds))


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
