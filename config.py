import os
import secrets

class Config:
    # Internal API key shared between all three servers
    # Set this in your environment: export QFACE_INTERNAL_KEY="your-strong-key"
    # If not set, a random one is generated (servers must share the same value, so always set it via env)
    INTERNAL_API_KEY = os.getenv("QFACE_INTERNAL_KEY", "CHANGE_ME_IN_PRODUCTION")

    # Recognition server
    RECOGNITION_API_URL = os.getenv("RECOGNITION_API_URL", "http://localhost:8001/upload-cropped")
    RECOGNITION_BASE_URL = os.getenv("RECOGNITION_BASE_URL", "http://localhost:8001")
    CAMERA_BASE = os.getenv("CAMERA_BASE_URL", "http://localhost:8000")

    # Door
    DOOR_API_URL = os.getenv("DOOR_API_URL", "http://192.168.1.6/trigger")
    DOOR_API_TIMEOUT = int(os.getenv("DOOR_API_TIMEOUT", 5))
    USE_DOOR_AUTH = os.getenv("USE_DOOR_AUTH", "false").lower() == "true"
    DOOR_API_KEY = os.getenv("DOOR_API_KEY", "")

    # Recognition tuning
    RECOGNITION_THRESHOLD = int(os.getenv("RECOGNITION_THRESHOLD", 80))

    # Camera
    FRAME_CACHE_DURATION = float(os.getenv("FRAME_CACHE_DURATION", 0.033))  # ~30fps
