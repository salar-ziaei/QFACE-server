"""
settings_manager.py
Shared settings manager — loaded by all three servers.
Camera and recognition servers call refresh() every 30 seconds.
"""
import sqlite3
import threading
import time
import logging

logger = logging.getLogger(__name__)

DEFAULTS = {
    # Door
    "door_url":               "http://192.168.1.6/trigger",
    "door_auth_key":          "",
    "door_use_auth":          "false",
    "door_auto_open":         "true",
    "door_success_delay":     "3.0",
    "door_error_delay":       "1.0",
    # Recognition
    "recognition_threshold":  "80",
    "margin_threshold":       "5.0",
    # YuNet
    "yunet_score_threshold":  "0.88",
    "yunet_nms_threshold":    "0.3",
    # Camera
    "send_interval":          "1.5",
    "frame_quality":          "75",
    # Crop region
    "crop_region_enabled":    "true",
    "crop_x_start":           "140",
    "crop_x_end":             "460",
    "crop_y_start":           "200",
    "crop_y_end":             "480",
    #Camera Rotations
    "camera_rotatation_angle":"0",
    "camera_mirror":          "false",
}

# Type casting map
TYPES = {
    "door_url":               str,
    "door_auth_key":          str,
    "door_use_auth":          lambda v: v.lower() == "true",
    "door_auto_open":         lambda v: v.lower() == "true",
    "door_success_delay":     float,
    "door_error_delay":       float,
    "recognition_threshold":  int,
    "margin_threshold":       float,
    "yunet_score_threshold":  float,
    "yunet_nms_threshold":    float,
    "send_interval":          float,
    "frame_quality":          int,
    "crop_region_enabled":    lambda v: v.lower() == "true",
    "crop_x_start":           int,
    "crop_x_end":             int,
    "crop_y_start":           int,
    "crop_y_end":             int,
    "camera_rotatation_angle":int,
    "camera_mirror":          lambda v: v.lower() == "true",
}


class SettingsManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._cache = {}
        self._lock = threading.Lock()
        self._init_table()
        self._load()

    def _init_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Insert defaults for any missing keys
        for k, v in DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, str(v))
            )
        conn.commit()
        conn.close()

    def _load(self):
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            conn.close()
            raw = {k: v for k, v in rows}
            casted = {}
            for k, cast in TYPES.items():
                raw_val = raw.get(k, DEFAULTS.get(k, ""))
                try:
                    casted[k] = cast(raw_val)
                except Exception:
                    casted[k] = cast(DEFAULTS[k])
            with self._lock:
                self._cache = casted
            logger.debug("Settings loaded from DB")
        except Exception as e:
            logger.error(f"Settings load error: {e}")

    def get(self, key, default=None):
        with self._lock:
            return self._cache.get(key, default)

    def all(self) -> dict:
        with self._lock:
            return dict(self._cache)

    def set(self, key: str, value) -> bool:
        if key not in DEFAULTS:
            return False
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value))
            )
            conn.commit()
            conn.close()
            self._load()
            return True
        except Exception as e:
            logger.error(f"Settings set error: {e}")
            return False

    def set_many(self, updates: dict) -> bool:
        invalid = [k for k in updates if k not in DEFAULTS]
        if invalid:
            logger.warning(f"Unknown settings keys: {invalid}")
        try:
            conn = sqlite3.connect(self.db_path)
            for k, v in updates.items():
                if k in DEFAULTS:
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                        (k, str(v))
                    )
            conn.commit()
            conn.close()
            self._load()
            return True
        except Exception as e:
            logger.error(f"Settings set_many error: {e}")
            return False

    def start_auto_refresh(self, interval: int = 30):
        """Reload settings from DB every N seconds (for camera/recognition servers)."""
        def loop():
            while True:
                time.sleep(interval)
                self._load()
        t = threading.Thread(target=loop, daemon=True)
        t.start()
        logger.info(f"Settings auto-refresh started (every {interval}s)")


# Singleton — import this in all servers
_instance: SettingsManager = None

def init_settings(db_path: str) -> SettingsManager:
    global _instance
    _instance = SettingsManager(db_path)
    return _instance

def get_settings() -> SettingsManager:
    return _instance
