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
    """Get the latest known location context for a user."""
    resolved = _resolve_user(user_id)
    if not resolved:
        return "Could not resolve user id for location lookup."
    context = location_service.get_location_context(resolved, max_age_hours=max_age_hours)
    return context or "No recent location data available."


@tool
def location_remember_place(label: str, radius_m: float = 180, user_id: Optional[str] = None):
    """
    Remember current location as a named place (example: home, office, gym).
    Uses latest tracked coordinates for this user.
    """
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
    """Return current location pattern analysis for debugging or proactive planning."""
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
