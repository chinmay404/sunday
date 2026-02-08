import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Dict, Optional


LOCATION_FILE = Path("llm/services/user_locations.json")


class LocationService:
    def __init__(self, location_file: Optional[Path] = None):
        self.location_file = location_file or LOCATION_FILE
        self._lock = Lock()
        self.locations: Dict[str, Dict] = {}
        self._load_locations()

    def _load_locations(self) -> None:
        with self._lock:
            if self.location_file.exists():
                try:
                    with open(self.location_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        self.locations = loaded if isinstance(loaded, dict) else {}
                except Exception:
                    self.locations = {}
            else:
                self.locations = {}

    def _save_locations(self) -> None:
        with self._lock:
            self.location_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self.location_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.locations, f, indent=2)
            os.replace(tmp_file, self.location_file)

    def update_location(
        self,
        user_id: str,
        latitude: float,
        longitude: float,
        chat_id: Optional[str] = None,
    ) -> None:
        now_ts = time.time()
        payload = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timestamp": now_ts,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now_ts)),
        }
        if chat_id:
            payload["chat_id"] = str(chat_id)

        with self._lock:
            self.locations[str(user_id)] = payload
            if chat_id:
                self.locations[str(chat_id)] = payload
        self._save_locations()

    def get_location(self, user_id: str, max_age_hours: Optional[float] = None) -> Optional[Dict]:
        self._load_locations()
        with self._lock:
            loc = self.locations.get(str(user_id))
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

    def get_location_string(self, user_id: str, max_age_hours: Optional[float] = None) -> str:
        loc = self.get_location(user_id, max_age_hours=max_age_hours)
        if not loc:
            return ""

        elapsed = max(0, int(time.time() - float(loc["timestamp"])))
        if elapsed < 3600:
            age = f"{elapsed // 60} mins ago"
        else:
            age = f"{elapsed // 3600} hours ago"

        lat = loc["latitude"]
        lon = loc["longitude"]
        return f"Last known location ({age}): lat={lat}, lon={lon}"
