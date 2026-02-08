import contextvars
import json
import math
import os
import time
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional


LOCATION_FILE = Path("llm/services/user_locations.json")
MAX_HISTORY_DAYS = 14
MIN_HISTORY_SAMPLE_SECONDS = 60
PATTERN_DWELL_RADIUS_M = 250.0
PATTERN_DWELL_MINUTES = 90
MAX_EVENT_DAYS = 21
MAX_EVENTS = 5000

CURRENT_LOCATION_USER_ID = contextvars.ContextVar("current_location_user_id", default=None)


def set_current_location_user_id(user_id: Optional[str]):
    return CURRENT_LOCATION_USER_ID.set(str(user_id) if user_id is not None else None)


def reset_current_location_user_id(token):
    CURRENT_LOCATION_USER_ID.reset(token)


def get_current_location_user_id() -> Optional[str]:
    value = CURRENT_LOCATION_USER_ID.get()
    return str(value) if value is not None else None


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


class LocationService:
    def __init__(self, location_file: Optional[Path] = None):
        self.location_file = location_file or LOCATION_FILE
        self._lock = RLock()
        self.data: Dict = {}
        self._load_locations()

    def _empty_data(self) -> Dict:
        return {
            "latest": {},
            "history": {},
            "places": {},
            "aliases": {},
            "meta": {"last_pattern_prompt": {}},
            "events": [],
        }

    def _normalize_data(self, loaded: Dict) -> Dict:
        if not isinstance(loaded, dict):
            return self._empty_data()

        # Backward compatibility: old format was {user_id: {latitude, longitude, ...}}
        if "latest" not in loaded and "history" not in loaded and "places" not in loaded:
            converted = self._empty_data()
            for user_id, payload in loaded.items():
                if not isinstance(payload, dict):
                    continue
                if "latitude" not in payload or "longitude" not in payload:
                    continue
                now_ts = float(payload.get("timestamp", time.time()))
                converted["latest"][str(user_id)] = {
                    "user_id": str(payload.get("user_id", user_id)),
                    "chat_id": str(payload.get("chat_id", user_id)),
                    "latitude": float(payload["latitude"]),
                    "longitude": float(payload["longitude"]),
                    "timestamp": now_ts,
                    "updated_at": payload.get(
                        "updated_at",
                        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now_ts)),
                    ),
                    "source": payload.get("source", "legacy"),
                }
            return converted

        normalized = self._empty_data()
        for key in normalized.keys():
            value = loaded.get(key)
            if isinstance(value, dict):
                normalized[key] = value

        if not isinstance(normalized["meta"], dict):
            normalized["meta"] = {"last_pattern_prompt": {}}
        if "last_pattern_prompt" not in normalized["meta"] or not isinstance(
            normalized["meta"].get("last_pattern_prompt"), dict
        ):
            normalized["meta"]["last_pattern_prompt"] = {}
        events = loaded.get("events")
        normalized["events"] = events if isinstance(events, list) else []
        return normalized

    def _load_locations(self) -> None:
        with self._lock:
            if self.location_file.exists():
                try:
                    with open(self.location_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        self.data = self._normalize_data(loaded)
                except Exception:
                    self.data = self._empty_data()
            else:
                self.data = self._empty_data()

    def _save_locations(self) -> None:
        with self._lock:
            self.location_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self.location_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp_file, self.location_file)

    def _resolve_user_id(self, user_id: str) -> str:
        with self._lock:
            aliases = self.data.get("aliases", {})
            return str(aliases.get(str(user_id), str(user_id)))

    def _prune_history_unlocked(self, user_id: str) -> None:
        history = self.data.get("history", {}).get(user_id, [])
        if not isinstance(history, list):
            self.data.setdefault("history", {})[user_id] = []
            return
        cutoff = time.time() - (MAX_HISTORY_DAYS * 86400)
        self.data["history"][user_id] = [
            p
            for p in history
            if isinstance(p, dict) and float(p.get("timestamp", 0)) >= cutoff
        ]

    def _append_event_unlocked(self, event_type: str, user_id: Optional[str], details: Optional[Dict] = None) -> None:
        events = self.data.setdefault("events", [])
        if not isinstance(events, list):
            events = []
            self.data["events"] = events
        now_ts = time.time()
        event = {
            "timestamp": now_ts,
            "event_type": str(event_type),
            "user_id": str(user_id) if user_id is not None else None,
            "details": details or {},
        }
        events.append(event)

        cutoff = now_ts - (MAX_EVENT_DAYS * 86400)
        self.data["events"] = [
            e for e in events if isinstance(e, dict) and float(e.get("timestamp", 0)) >= cutoff
        ][-MAX_EVENTS:]

    def update_location(
        self,
        user_id: str,
        latitude: float,
        longitude: float,
        chat_id: Optional[str] = None,
        source: str = "telegram",
    ) -> None:
        self._load_locations()
        now_ts = time.time()
        uid = str(user_id)
        cid = str(chat_id) if chat_id is not None else uid

        latest_payload = {
            "user_id": uid,
            "chat_id": cid,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timestamp": now_ts,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now_ts)),
            "source": source,
        }

        with self._lock:
            self.data.setdefault("latest", {})[uid] = latest_payload
            self.data.setdefault("aliases", {})[cid] = uid
            history = self.data.setdefault("history", {}).setdefault(uid, [])

            append_point = True
            if history:
                last = history[-1]
                dt = now_ts - float(last.get("timestamp", 0))
                dist = _haversine_meters(
                    float(last.get("latitude", latitude)),
                    float(last.get("longitude", longitude)),
                    float(latitude),
                    float(longitude),
                )
                if dt < MIN_HISTORY_SAMPLE_SECONDS and dist < 10:
                    append_point = False

            if append_point:
                history.append(
                    {
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                        "timestamp": now_ts,
                    }
                )
                self._prune_history_unlocked(uid)
                self._append_event_unlocked(
                    event_type="location_update",
                    user_id=uid,
                    details={
                        "chat_id": cid,
                        "latitude": round(float(latitude), 6),
                        "longitude": round(float(longitude), 6),
                        "source": source,
                    },
                )

        self._save_locations()

    def list_tracked_users(self) -> List[str]:
        self._load_locations()
        with self._lock:
            latest = self.data.get("latest", {})
            users = set()
            for key, payload in latest.items():
                if isinstance(payload, dict):
                    uid = str(payload.get("user_id", key))
                else:
                    uid = str(key)
                # Telegram user ids are positive; skip chat/group ids accidentally persisted as users.
                if uid.startswith("-"):
                    continue
                users.add(uid)
            return sorted(users)

    def get_chat_id_for_user(self, user_id: str) -> Optional[str]:
        loc = self.get_location(user_id, max_age_hours=None)
        if not loc:
            return None
        chat_id = loc.get("chat_id")
        return str(chat_id) if chat_id is not None else None

    def get_location(self, user_id: str, max_age_hours: Optional[float] = None) -> Optional[Dict]:
        self._load_locations()
        resolved_user = self._resolve_user_id(str(user_id))
        with self._lock:
            loc = self.data.get("latest", {}).get(resolved_user)
        if not loc:
            return None
        if max_age_hours is not None:
            try:
                max_age_secs = float(max_age_hours) * 3600.0
                if (time.time() - float(loc.get("timestamp", 0))) > max_age_secs:
                    return None
            except Exception:
                return None
        return loc

    def get_history(self, user_id: str, lookback_hours: float = 24) -> List[Dict]:
        self._load_locations()
        resolved_user = self._resolve_user_id(str(user_id))
        cutoff = time.time() - max(1.0, float(lookback_hours)) * 3600.0
        with self._lock:
            history = self.data.get("history", {}).get(resolved_user, [])
            if not isinstance(history, list):
                return []
            return [p for p in history if float(p.get("timestamp", 0)) >= cutoff]

    def _match_place_unlocked(self, user_id: str, lat: float, lon: float) -> Optional[Dict]:
        places = self.data.get("places", {}).get(user_id, {})
        if not isinstance(places, dict):
            return None
        best = None
        for label_key, payload in places.items():
            if not isinstance(payload, dict):
                continue
            p_lat = payload.get("latitude")
            p_lon = payload.get("longitude")
            radius = float(payload.get("radius_m", 180))
            if p_lat is None or p_lon is None:
                continue
            dist = _haversine_meters(float(lat), float(lon), float(p_lat), float(p_lon))
            if dist <= radius:
                candidate = {
                    "label_key": str(label_key),
                    "label": str(payload.get("label", label_key)),
                    "distance_m": round(dist, 1),
                    "radius_m": radius,
                }
                if best is None or dist < best["distance_m"]:
                    best = candidate
        return best

    def resolve_current_place(self, user_id: str, max_age_hours: float = 30) -> Optional[Dict]:
        loc = self.get_location(user_id, max_age_hours=max_age_hours)
        if not loc:
            return None
        resolved_user = self._resolve_user_id(str(user_id))
        with self._lock:
            return self._match_place_unlocked(
                resolved_user,
                float(loc["latitude"]),
                float(loc["longitude"]),
            )

    def list_places(self, user_id: Optional[str] = None) -> List[Dict]:
        resolved_user = self._resolve_user_id(str(user_id or get_current_location_user_id() or ""))
        if not resolved_user:
            return []
        self._load_locations()
        with self._lock:
            places = self.data.get("places", {}).get(resolved_user, {})
            if not isinstance(places, dict):
                return []
            out = []
            for label_key, payload in places.items():
                if not isinstance(payload, dict):
                    continue
                out.append(
                    {
                        "label": str(payload.get("label", label_key)),
                        "latitude": payload.get("latitude"),
                        "longitude": payload.get("longitude"),
                        "radius_m": payload.get("radius_m", 180),
                        "created_at": payload.get("created_at"),
                    }
                )
            return sorted(out, key=lambda p: p["label"].lower())

    def remember_place(
        self,
        label: str,
        user_id: Optional[str] = None,
        radius_m: float = 180,
        max_age_hours: float = 30,
    ) -> Dict:
        uid = str(user_id or get_current_location_user_id() or "").strip()
        if not uid:
            raise ValueError("Could not resolve user_id for remembering place.")
        place_label = (label or "").strip()
        if not place_label:
            raise ValueError("label is required.")

        loc = self.get_location(uid, max_age_hours=max_age_hours)
        if not loc:
            raise ValueError("No recent location found to remember.")

        label_key = place_label.lower()
        self._load_locations()
        resolved_user = self._resolve_user_id(uid)
        payload = {
            "label": place_label,
            "latitude": float(loc["latitude"]),
            "longitude": float(loc["longitude"]),
            "radius_m": float(radius_m),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time())),
        }
        with self._lock:
            self.data.setdefault("places", {}).setdefault(resolved_user, {})[label_key] = payload
            self._append_event_unlocked(
                event_type="place_added",
                user_id=resolved_user,
                details={
                    "label": place_label,
                    "latitude": round(float(payload["latitude"]), 6),
                    "longitude": round(float(payload["longitude"]), 6),
                    "radius_m": float(payload["radius_m"]),
                },
            )
        self._save_locations()
        return payload

    def forget_place(self, label: str, user_id: Optional[str] = None) -> bool:
        uid = str(user_id or get_current_location_user_id() or "").strip()
        if not uid:
            return False
        label_key = (label or "").strip().lower()
        if not label_key:
            return False
        self._load_locations()
        resolved_user = self._resolve_user_id(uid)
        removed = False
        with self._lock:
            places = self.data.setdefault("places", {}).setdefault(resolved_user, {})
            if label_key in places:
                del places[label_key]
                removed = True
                self._append_event_unlocked(
                    event_type="place_removed",
                    user_id=resolved_user,
                    details={"label": label},
                )
        if removed:
            self._save_locations()
        return removed

    def _compute_dwell_minutes(
        self,
        user_id: str,
        current_lat: float,
        current_lon: float,
        lookback_hours: float = 6,
    ) -> float:
        history = self.get_history(user_id, lookback_hours=lookback_hours)
        if not history:
            return 0.0
        history = sorted(history, key=lambda p: float(p.get("timestamp", 0)))
        last_ts = float(history[-1].get("timestamp", time.time()))
        start_ts = last_ts
        for point in reversed(history):
            lat = float(point.get("latitude", current_lat))
            lon = float(point.get("longitude", current_lon))
            distance = _haversine_meters(current_lat, current_lon, lat, lon)
            if distance > PATTERN_DWELL_RADIUS_M:
                break
            start_ts = float(point.get("timestamp", start_ts))
        return max(0.0, (last_ts - start_ts) / 60.0)

    def analyze_pattern(
        self,
        user_id: str,
        max_age_hours: float = 6,
        dwell_minutes_threshold: float = PATTERN_DWELL_MINUTES,
    ) -> Dict:
        loc = self.get_location(user_id, max_age_hours=max_age_hours)
        if not loc:
            return {"available": False, "reason": "No recent location data."}

        uid = self._resolve_user_id(str(user_id))
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])
        place = self.resolve_current_place(uid, max_age_hours=max_age_hours)
        dwell_minutes = self._compute_dwell_minutes(uid, lat, lon, lookback_hours=max_age_hours)

        unknown_area = place is None and dwell_minutes >= float(dwell_minutes_threshold)
        reason_key = None
        summary = ""
        if place:
            summary = f"At saved place '{place['label']}' ({int(place['distance_m'])}m from center)."
            reason_key = f"known:{place['label_key']}"
        else:
            summary = f"In unsaved area for about {int(dwell_minutes)} minutes."
            reason_key = f"unknown:{round(lat, 3)}:{round(lon, 3)}"

        return {
            "available": True,
            "user_id": uid,
            "chat_id": loc.get("chat_id"),
            "latitude": lat,
            "longitude": lon,
            "current_place": place,
            "dwell_minutes": round(dwell_minutes, 1),
            "unusual": unknown_area,
            "summary": summary,
            "reason_key": reason_key,
            "prompt_hint": (
                "Ask why he's there and whether this should be remembered as a named place."
                if unknown_area
                else "No proactive check-in needed."
            ),
        }

    def should_prompt_about_pattern(
        self,
        user_id: str,
        cooldown_hours: float = 8,
        max_age_hours: float = 6,
    ) -> Optional[Dict]:
        analysis = self.analyze_pattern(user_id, max_age_hours=max_age_hours)
        if not analysis.get("available") or not analysis.get("unusual"):
            return None

        uid = str(analysis["user_id"])
        now_ts = time.time()
        self._load_locations()
        with self._lock:
            meta = self.data.setdefault("meta", {}).setdefault("last_pattern_prompt", {})
            last = meta.get(uid)
            if isinstance(last, dict):
                last_ts = float(last.get("timestamp", 0))
                last_key = str(last.get("reason_key", ""))
                in_cooldown = (now_ts - last_ts) < float(cooldown_hours) * 3600.0
                if in_cooldown and last_key == str(analysis.get("reason_key", "")):
                    return None
        return analysis

    def mark_pattern_prompt_sent(self, user_id: str, reason_key: str) -> None:
        uid = self._resolve_user_id(str(user_id))
        now_ts = time.time()
        self._load_locations()
        with self._lock:
            meta = self.data.setdefault("meta", {}).setdefault("last_pattern_prompt", {})
            meta[uid] = {"timestamp": now_ts, "reason_key": str(reason_key)}
            self._append_event_unlocked(
                event_type="pattern_prompt_sent",
                user_id=uid,
                details={"reason_key": str(reason_key)},
            )
        self._save_locations()

    def get_location_string(self, user_id: str, max_age_hours: Optional[float] = None) -> str:
        loc = self.get_location(user_id, max_age_hours=max_age_hours)
        if not loc:
            return ""

        elapsed = max(0, int(time.time() - float(loc["timestamp"])))
        if elapsed < 3600:
            age = f"{elapsed // 60} mins ago"
        else:
            age = f"{elapsed // 3600} hours ago"

        lat = float(loc["latitude"])
        lon = float(loc["longitude"])
        place = self.resolve_current_place(user_id, max_age_hours=max_age_hours or 30)
        if place:
            return (
                f"Last known location ({age}): lat={lat}, lon={lon}. "
                f"Current saved place: {place['label']}."
            )
        return f"Last known location ({age}): lat={lat}, lon={lon}."

    def get_location_context(self, user_id: str, max_age_hours: float = 30) -> str:
        base = self.get_location_string(user_id, max_age_hours=max_age_hours)
        if not base:
            return ""

        places = self.list_places(user_id)
        place_names = [p["label"] for p in places]
        pattern = self.analyze_pattern(user_id, max_age_hours=min(max_age_hours, 6))

        parts = [base]
        if place_names:
            parts.append(f"Saved places: {', '.join(place_names[:8])}.")
        if pattern.get("available"):
            parts.append(f"Pattern snapshot: {pattern.get('summary')}")
        return " ".join(parts)

    def get_recent_events(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> List[Dict]:
        self._load_locations()
        max_items = max(1, min(int(limit), 200))
        resolved_user = None
        if user_id is not None:
            resolved_user = self._resolve_user_id(str(user_id))
        with self._lock:
            events = self.data.get("events", [])
            if not isinstance(events, list):
                return []
            filtered = []
            for e in events:
                if not isinstance(e, dict):
                    continue
                if resolved_user and str(e.get("user_id") or "") != resolved_user:
                    continue
                if event_type and str(e.get("event_type") or "") != str(event_type):
                    continue
                filtered.append(e)
            return filtered[-max_items:]

    def get_debug_summary(self, user_id: Optional[str] = None) -> Dict:
        self._load_locations()
        resolved_user = None
        if user_id:
            resolved_user = self._resolve_user_id(str(user_id))

        with self._lock:
            if resolved_user:
                latest = self.data.get("latest", {}).get(resolved_user)
                history = self.data.get("history", {}).get(resolved_user, [])
                places = self.data.get("places", {}).get(resolved_user, {})
                event_count = len(
                    [
                        e
                        for e in self.data.get("events", [])
                        if isinstance(e, dict) and str(e.get("user_id") or "") == resolved_user
                    ]
                )
                return {
                    "user_id": resolved_user,
                    "has_latest": latest is not None,
                    "latest": latest,
                    "history_points": len(history) if isinstance(history, list) else 0,
                    "saved_places": sorted(list(places.keys())) if isinstance(places, dict) else [],
                    "event_count": event_count,
                }

            latest = self.data.get("latest", {})
            tracked_users = []
            if isinstance(latest, dict):
                seen = set()
                for key, payload in latest.items():
                    if isinstance(payload, dict):
                        uid = str(payload.get("user_id", key))
                    else:
                        uid = str(key)
                    if uid.startswith("-") or uid in seen:
                        continue
                    seen.add(uid)
                    tracked_users.append(uid)
                tracked_users = sorted(tracked_users)
            places_by_user = {}
            for uid, places in self.data.get("places", {}).items():
                if isinstance(places, dict):
                    places_by_user[str(uid)] = sorted(list(places.keys()))
            return {
                "tracked_users": tracked_users,
                "total_events": len(self.data.get("events", []))
                if isinstance(self.data.get("events", []), list)
                else 0,
                "places_by_user": places_by_user,
            }
