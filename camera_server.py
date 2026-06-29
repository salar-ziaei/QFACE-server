from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import cv2
import numpy as np
import requests
import threading
import time
import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import Config
from settings_manager import init_settings, get_settings

# ---------- Logging ----------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(LOG_DIR, "camera.log"), maxBytes=5 * 1024 * 1024, backupCount=3
        ),
    ],
)
logger = logging.getLogger(__name__)

DB_PATH = "logs/users.db"
settings = init_settings(DB_PATH)
settings.start_auto_refresh(30)

app = FastAPI(title="QFACE - Camera Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Internal API key security ----------
INTERNAL_KEY = Config.INTERNAL_API_KEY
OPEN_PATHS = {"/health"}


@app.middleware("http")
async def verify_internal_key(request: Request, call_next):
    if request.url.path in OPEN_PATHS:
        return await call_next(request)
    key = request.headers.get("X-Internal-Key")
    if key != INTERNAL_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)


# ---------- YuNet ----------
YUNET_MODEL = "models/face_detection_yunet_2023mar.onnx"


# ---------- Camera ----------
class CameraCapture:
    def __init__(self):
        s = get_settings()
        self.camera_rotatation_angle = s.get("camera_rotatation_angle", 0)
        self.camera_mirror = s.get("camera_mirror", False)
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self.processor_thread = None
        self.raw_frame = None  # raw frame (no overlay)
        self.raw_lock = threading.Lock()
        self.width = 640
        self.height = 480
        self.fps = 30

    def start(self, source=0):
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            logger.error(f"Cannot open camera {source}")
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        # Start background processing loop (no overlay)
        self._start_processing_loop()
        logger.info("Camera started")
        return True

    def _capture_loop(self):
        logger.info("Camera capture thread started")
        s = get_settings()
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                self.camera_rotatation_angle = s.get("camera_rotatation_angle", 0)
                self.camera_mirror = s.get("camera_mirror", False)
                angle = self.camera_rotatation_angle
                if angle != 0:
                    h, w = frame.shape[:2]
                    center = (w // 2, h // 2)
                    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
                    # Compute new bounding dimensions to avoid cropping
                    cos = abs(rot_mat[0, 0])
                    sin = abs(rot_mat[0, 1])
                    new_w = int((h * sin) + (w * cos))
                    new_h = int((h * cos) + (w * sin))
                    rot_mat[0, 2] += (new_w / 2) - center[0]
                    rot_mat[1, 2] += (new_h / 2) - center[1]
                    frame = cv2.warpAffine(frame, rot_mat, (new_w, new_h))
                if self.camera_mirror:
                    frame = cv2.flip(frame, 1)
                    # frame = cv2.rotate(frame, cv2.ROTATE_180)
                with self.lock:
                    self.frame = frame
            else:
                logger.warning("Frame read failed, retrying...")
                time.sleep(0.1)
        logger.info("Camera capture thread stopped")

    def _start_processing_loop(self):
        """Continuously process frames in background (no overlay)."""

        def loop():
            logger.info("Background processing loop started")
            while self.running:
                frame = self.get_frame()
                if frame is not None:
                    # Process frame: detection + recognition, store raw frame
                    processed = face_processor.process_raw(frame)
                    with self.raw_lock:
                        self.raw_frame = processed
                time.sleep(0.05)
            logger.info("Background processing loop stopped")

        self.processor_thread = threading.Thread(target=loop, daemon=True)
        self.processor_thread.start()

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def get_raw_frame(self):
        with self.raw_lock:
            return self.raw_frame.copy() if self.raw_frame is not None else None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


# ---------- Face detection & recognition ----------
class FaceProcessor:
    def __init__(self):
        s = get_settings()
        self.last_send_time = 0
        self.send_interval = s.get("send_interval", 1.5)
        self.processing = False
        self.lock = threading.Lock()
        self.last_result = None
        self.last_faces = []
        self.last_faces_lock = threading.Lock()
        self.result_display_until = 0
        self.last_faces = []  # store faces for overlay
        self.crop_region_y_start = s.get("crop_y_start", 200)
        self.crop_region_y_end = s.get("crop_y_end", 480)
        self.crop_region_x_start = s.get("crop_x_start", 140)
        self.crop_region_x_end = s.get("crop_x_end", 460)
        self.face_detected = False
        self.face_detected_name = "Unknown"
        self.face_detected_image = None
        self.face_is_recognised = False
        self.face_access_allowed = False
        self.face_confidence = 0.0
        self.face_detected_time = 0
        if not os.path.exists(YUNET_MODEL):
            logger.error(f"YuNet model not found: {YUNET_MODEL}")
            self.face_detector = None
            return None
        try:
            crop_w = self.crop_region_x_end - self.crop_region_x_start
            crop_h = self.crop_region_y_end - self.crop_region_y_start
            self.face_detector = cv2.FaceDetectorYN.create(
                YUNET_MODEL,
                "",
                (crop_w, crop_h),
                score_threshold=s.get("yunet_score_threshold", 0.88),
                nms_threshold=s.get("yunet_nms_threshold", 0.3),
                top_k=5,
            )
            logger.info(f"YuNet loaded ({crop_w}x{crop_h})")
        except Exception as e:
            logger.error(f"YuNet load error: {e}")
            self.face_detector = None

    def _reload_yunet(self,):
        s = get_settings()
        self.crop_region_y_start = s.get("crop_y_start", 200)
        self.crop_region_y_end = s.get("crop_y_end", 480)
        self.crop_region_x_start = s.get("crop_x_start", 140)
        self.crop_region_x_end = s.get("crop_x_end", 460)
        try:
            crop_w = self.crop_region_x_end - self.crop_region_x_start
            crop_h = self.crop_region_y_end - self.crop_region_y_start
            self.face_detector = cv2.FaceDetectorYN.create(
                YUNET_MODEL,
                "",
                (crop_w, crop_h),
                score_threshold=s.get("yunet_score_threshold", 0.88),
                nms_threshold=s.get("yunet_nms_threshold", 0.3),
                top_k=5,
            )
            logger.info(f"YuNet loaded ({crop_w}x{crop_h})")
        except Exception as e:
            logger.error(f"YuNet load error: {e}")
            self.face_detector = None

    def detect_faces(self, frame):
        if self.face_detector is None:
            return []
        try:
            # Crop the region of interest
            s = get_settings()
            if s.get("crop_region_enabled", True):
                x1 = s.get("crop_x_start", self.crop_region_x_start)
                x2 = s.get("crop_x_end", self.crop_region_x_end)
                y1 = s.get("crop_y_start", self.crop_region_y_start)
                y2 = s.get("crop_y_end", self.crop_region_y_end)
                cropped = frame[y1:y2, x1:x2]
                x_offset, y_offset = x1, y1
            else:
                cropped = frame
                x_offset, y_offset = 0, 0
            if cropped.size == 0:
                return []

            _, faces = self.face_detector.detect(cropped)
            if faces is None:
                return []

            # Adjust face coordinates back to original frame
            adjusted_faces = []
            for face in faces:
                x, y, w, h = face[:4].astype(int)
                x += x_offset
                y += y_offset
                landmarks = face[4:14].reshape(5, 2).astype(int)
                landmarks[:, 0] += x_offset
                landmarks[:, 1] += y_offset
                adjusted_face = face.copy()
                adjusted_face[0] = x
                adjusted_face[1] = y
                adjusted_face[4:14] = landmarks.reshape(10)
                adjusted_faces.append(adjusted_face)

            return adjusted_faces
        except Exception as e:
            logger.error(f"Detection error: {e}")
            self._reload_yunet()
            return []

    def crop_face(self, frame, face):
        x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
        pad = int(min(w, h) * 0.15)
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(frame.shape[1], x + w + pad)
        y2 = min(frame.shape[0], y + h + pad)
        return frame[y1:y2, x1:x2]

    def send_to_recognition(self, crop):
        try:
            _, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            resp = requests.post(
                Config.RECOGNITION_API_URL,
                files={"file": ("face.jpg", buf.tobytes(), "image/jpeg")},
                headers={"X-Internal-Key": Config.INTERNAL_API_KEY},
                timeout=3,
            )
            if resp.status_code == 200:
                now = time.time()
                result = resp.json()
                self.last_result = result
                self.result_display_until = now + 3
                self.face_detected_name = result.get("prediction")
                self.face_detected_image = result.get("image")
                self.face_is_recognised = result.get("is_recognised")
                self.face_access_allowed = result.get("access_allowed")
                self.face_confidence = result.get("confidence")
                self.face_detected_time = now
                if (
                    self.face_is_recognised
                    and self.face_access_allowed
                    and get_settings().get("door_auto_open", True)
                ):
                    threading.Thread(
                        target=self._trigger_door, args=(result,), daemon=True
                    ).start()
                logger.info(
                    f"Recognition: {result.get('prediction')} ({result.get('confidence', 0):.1f}%)"
                )
        except Exception as e:
            logger.error(f"Recognition send error: {e}")
        finally:
            with self.lock:
                self.processing = False

    def _trigger_door(self, result):
        s = get_settings()
        url = s.get("door_url", Config.DOOR_API_URL)
        try:
            if s.get("door_use_auth", False) and s.get("door_auth_key", ""):
                sep = "&" if "?" in url else "?"
                url += f"{sep}key={s.get('door_auth_key')}"
            requests.get(url, timeout=Config.DOOR_API_TIMEOUT)
            requests.post(
                f"{Config.RECOGNITION_BASE_URL}/api/door_log",
                json={
                    "person": result.get("prediction"),
                    "action": "door_open",
                    "result": "success",
                    "confidence": result.get("confidence", 0),
                },
                headers={"X-Internal-Key": Config.INTERNAL_API_KEY},
                timeout=3,
            )
            logger.info(f"Door triggered for {result.get('prediction')}")
            time.sleep(s.get("door_success_delay", 3.0))
        except Exception as e:
            logger.error(f"Door trigger error: {e}")
            time.sleep(s.get("door_error_delay", 1.0))
        finally:
            with self.lock:
                self.processing = False

    def process_raw(self, frame):
        """Process frame: detect faces, send to recognition, return raw frame (no overlay)."""
        now = time.time()
        faces = self.detect_faces(frame)
        if faces is not None and len(faces) > 0:
            self.face_detected = True
            self.face_detected_time = time.time()
        with self.last_faces_lock:
            self.last_faces = faces

        if faces is not None and len(faces) > 0:
            with self.lock:
                interval = get_settings().get("send_interval", self.send_interval)
                can_process = (
                    not self.processing and (now - self.last_send_time) >= interval
                )
            if can_process:
                best = max(faces, key=lambda f: float(f[14]) if len(f) > 14 else 0)
                crop = self.crop_face(frame, best)
                if crop.size > 0:
                    with self.lock:
                        self.processing = True
                        self.last_send_time = now
                    threading.Thread(
                        target=self.send_to_recognition, args=(crop,), daemon=True
                    ).start()

        return frame  # return raw frame without overlay

    def draw_overlay(self, frame):
        """Draw overlays on the frame (bounding boxes, labels, etc.)."""
        annotated = frame.copy()
        now = time.time()
        with self.last_faces_lock:
            faces = list(self.last_faces)

        for face in faces:
            x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
            score = float(face[14]) if len(face) > 14 else 0

            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # Draw landmarks
            landmarks = face[4:14].reshape(5, 2).astype(int)
            for lm in landmarks:
                cv2.circle(annotated, tuple(lm), 2, (0, 200, 255), -1)

            # Overlay result if recent
            if self.last_result and now < self.result_display_until:
                name = self.last_result.get("prediction", "")
                conf = self.last_result.get("confidence", 0)
                allowed = self.last_result.get("access_allowed", False)
                is_rec = self.last_result.get("is_recognised", False)
                label = f"{name} {conf:.0f}%" if is_rec else "Unknown"
                col = (0, 255, 0) if (is_rec and allowed) else (0, 0, 255)
                cv2.putText(
                    annotated, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2
                )
                if is_rec and allowed:
                    cv2.putText(
                        annotated,
                        "ACCESS GRANTED",
                        (x, y + h + 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                    )
                elif is_rec and not allowed:
                    cv2.putText(
                        annotated,
                        "OUTSIDE HOURS",
                        (x, y + h + 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 165, 255),
                        2,
                    )

        # FPS overlay
        cv2.putText(
            annotated,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )
        cv2.putText(
            annotated,
            f"Faces: {len(faces)}",
            (10, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
            1,
        )

        return annotated


face_processor = FaceProcessor()
camera = CameraCapture()


# ---------- Stream ----------
def generate_frames():
    frame_interval = Config.FRAME_CACHE_DURATION
    last_frame_time = 0
    while True:
        now = time.time()
        if now - last_frame_time < frame_interval:
            time.sleep(0.005)
            continue
        raw = camera.get_raw_frame()
        if raw is None:
            time.sleep(0.01)
            continue
        try:
            # Draw overlay here (only when streaming)
            annotated = face_processor.draw_overlay(raw)
            quality = get_settings().get("frame_quality", 75)
            _, buf = cv2.imencode(
                ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            last_frame_time = now
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
        except Exception as e:
            logger.error(f"Stream error: {e}")
            time.sleep(0.1)


@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(
        generate_frames(), media_type="multipart/x-mixed-replace;boundary=frame"
    )


@app.get("/stream")
async def stream():
    return StreamingResponse(
        generate_frames(), media_type="multipart/x-mixed-replace;boundary=frame"
    )


@app.get("/api/face_detected")
async def face_detected():
    # Reset flag after 3 seconds of no detection
    now = time.time()
    if face_processor.face_detected and now - face_processor.face_detected_time > 3:
        face_processor.face_detected = False
        face_processor.face_detected_name = "Unknown"
        face_processor.face_detected_image = None
        face_processor.face_is_recognised = False
        face_processor.face_access_allowed = False
        face_processor.face_confidence = 0.0
    return {
        "detected": face_processor.face_detected,
        "name": face_processor.face_detected_name,
        "image": face_processor.face_detected_image,
        "recognised": face_processor.face_is_recognised,
        "allowed": face_processor.face_access_allowed,
        "confidence": face_processor.face_confidence
    }


@app.get("/api/status")
async def status():
    return {
        "camera_active": camera.running,
        "yunet_loaded": face_processor.face_detector is not None,
        "last_result": face_processor.last_result,
        "timestamp": datetime.datetime.now().isoformat(),
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "camera": camera.running,
        "yunet": face_processor.face_detector is not None,
    }


@app.post("/api/open_door")
async def manual_open_door(request: Request):
    try:
        data = (
            await request.json()
            if request.headers.get("content-type") == "application/json"
            else {}
        )
        door_id = data.get("door_id", 1)
        logger.info(f"Manual door open request for door {door_id}")

        url = Config.DOOR_API_URL
        if Config.USE_DOOR_AUTH and Config.DOOR_API_KEY:
            sep = "&" if "?" in url else "?"
            url += f"{sep}key={Config.DOOR_API_KEY}"

        resp = requests.get(url, timeout=Config.DOOR_API_TIMEOUT)
        if resp.status_code == 200:
            # Log door event
            try:
                requests.post(
                    f"{Config.RECOGNITION_BASE_URL}/api/door_log",
                    json={
                        "person": "Manual",
                        "action": "door_open",
                        "result": "success",
                        "confidence": 100,
                    },
                    headers={"X-Internal-Key": Config.INTERNAL_API_KEY},
                    timeout=3,
                )
            except:
                pass
            logger.info("Manual door triggered")
            return JSONResponse({"success": True, "message": "Door opened"})
        else:
            logger.error(f"Door API responded with {resp.status_code}")
            return JSONResponse(
                {"success": False, "message": f"Door API error: {resp.status_code}"},
                status_code=500,
            )
    except requests.exceptions.Timeout:
        logger.error("Door API timeout")
        return JSONResponse(
            {"success": False, "message": "Door API timeout"}, status_code=504
        )
    except Exception as e:
        logger.error(f"Manual door error: {e}")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.on_event("startup")
async def startup():
    camera.start(0)
    logger.info("Camera server started")


@app.on_event("shutdown")
async def shutdown():
    camera.stop()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
