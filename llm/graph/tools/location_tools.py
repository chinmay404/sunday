from typing import Optional

from langchain_core.tools import tool

from llm.services.location_service import (
    LocationService,
    get_current_location_user_id,
)


location_service = LocationService()


def _resolve_user(user_id: Optional[str]) -> Optional[str]:
    resolved = (user_id or "").strip()
    if resolved:
        return resolved
    return get_current_location_user_id()


@tool
def location_current_status(user_id: Optional[str] = None, max_age_hours: float = 30):
    """Get current location context: coordinates, place, address."""
    resolved = _resolve_user(user_id)
    if not resolved:
        return "Could not resolve user id for location lookup."
    context = location_service.get_location_context(resolved, max_age_hours=max_age_hours)
    return context or "No recent location data available."


@tool
def location_remember_place(label: str, radius_m: float = 180, user_id: Optional[str] = None):
    """Save current location as a named place (home, office, gym, etc)."""
    resolved = _resolve_user(user_id)
    if not resolved:
        return "Could not resolve user id. Provide user_id explicitly."
    try:
        place = location_service.remember_place(
            label=label,
            user_id=resolved,
            radius_m=radius_m,
        )
        return (
            f"Saved place '{place['label']}' at lat={place['latitude']}, "
            f"lon={place['longitude']} with radius {place['radius_m']}m."
        )
    except Exception as exc:
        return f"Failed to save place: {exc}"


@tool
def location_list_places(user_id: Optional[str] = None):
    """List saved named places for this user."""
    resolved = _resolve_user(user_id)
    if not resolved:
        return "Could not resolve user id for place listing."
    places = location_service.list_places(resolved)
    if not places:
        return "No saved places."
    lines = ["Saved places:"]
    for p in places:
        lines.append(
            f"- {p['label']}: lat={p['latitude']}, lon={p['longitude']}, radius={p['radius_m']}m"
        )
    return "\n".join(lines)


@tool
def location_forget_place(label: str, user_id: Optional[str] = None):
    """Delete a saved named place for this user."""
    resolved = _resolve_user(user_id)
    if not resolved:
        return "Could not resolve user id."
    removed = location_service.forget_place(label=label, user_id=resolved)
    if removed:
        return f"Removed saved place '{label}'."
    return f"Could not find saved place '{label}'."


@tool
def location_pattern_report(user_id: Optional[str] = None):
    """Analyze current location patterns: dwell time, unusual activity."""
    resolved = _resolve_user(user_id)
    if not resolved:
        return "Could not resolve user id."
    report = location_service.analyze_pattern(resolved)
    if not report.get("available"):
        return "No recent location data available."
    place = report.get("current_place")
    place_text = place["label"] if place else "unsaved area"
    return (
        f"Current area: {place_text}. "
        f"Dwell: {report.get('dwell_minutes')} minutes. "
        f"Unusual: {report.get('unusual')}. "
        f"Summary: {report.get('summary')}"
    )


@tool
def location_current_address(user_id: Optional[str] = None, max_age_hours: float = 30):
    """Get human-readable address for current coordinates."""
    resolved = _resolve_user(user_id)
    if not resolved:
        return "Could not resolve user id."
    # Use get_location_string which does lazy geocode if address is missing
    result = location_service.get_location_string(resolved, max_age_hours=max_age_hours)
    if not result:
        return "No recent location data available."
    return result


@tool
def location_recent_events(user_id: Optional[str] = None, limit: int = 20, event_type: str = ""):
    """Show recent location events (updates, place changes, observer prompts)."""
    resolved = _resolve_user(user_id)
    chosen_type = event_type.strip() or None
    events = location_service.get_recent_events(user_id=resolved, limit=limit, event_type=chosen_type)
    if not events:
        return "No recent location events."
    lines = ["Recent location events:"]
    for event in events:
        ts = event.get("timestamp")
        evt_type = event.get("event_type")
        uid = event.get("user_id")
        details = event.get("details") or {}
        lines.append(f"- ts={ts} type={evt_type} user={uid} details={details}")
    return "\n".join(lines)


@tool
def location_debug_summary(user_id: Optional[str] = None):
    """Debug: show tracked users, latest point, places, event counts."""
    resolved = _resolve_user(user_id)
    summary = location_service.get_debug_summary(user_id=resolved)
    return str(summary)
