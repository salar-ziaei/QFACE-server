from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    PlainTextResponse,
)
from fastapi.responses import StreamingResponse, Response as FastAPIResponse
import httpx
from fastapi.staticfiles import StaticFiles
import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional
import shutil
import time
import threading
import requests as req_lib
from config import Config
from settings_manager import init_settings, get_settings, DEFAULTS, TYPES
from fastapi.templating import Jinja2Templates

# ---------- Logging ----------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(LOG_DIR, "main.log"), maxBytes=10 * 1024 * 1024, backupCount=5
        ),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="QFACE - Main Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Folders ----------
UPLOAD_FOLDER = "upload"
RECOGNISED_FOLDER = os.path.join(UPLOAD_FOLDER, "recognised")
UNRECOGNISED_FOLDER = os.path.join(UPLOAD_FOLDER, "unrecognised")
DATABASE_FOLDER = "database"
for d in [
    UPLOAD_FOLDER,
    RECOGNISED_FOLDER,
    UNRECOGNISED_FOLDER,
    DATABASE_FOLDER,
    LOG_DIR,
]:
    os.makedirs(d, exist_ok=True)

DB_PATH = os.path.join(LOG_DIR, "users.db")
RECOG_DB_PATH = os.path.join(LOG_DIR, "recognition.db")
INTERNAL_KEY = Config.INTERNAL_API_KEY
RECOG_BASE = Config.RECOGNITION_BASE_URL
CAMERA_BASE = Config.CAMERA_BASE


# ---------- Database ----------
def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        entry_start_time TEXT DEFAULT '00:00',
        entry_end_time TEXT DEFAULT '23:59',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at)")
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        # SHA-256 for now — note in README to change on first login
        c.execute(
            "INSERT INTO users (username, password, is_admin) VALUES (?,?,?)",
            ("admin", hashlib.sha256("admin123".encode()).hexdigest(), 1),
        )
        conn.commit()
        logger.warning("Default admin user created — change password immediately!")
    conn.commit()
    conn.close()


init_database()
settings = init_settings(DB_PATH)


# ---------- Session helpers ----------
def create_session(username: str, days: int = 7) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO sessions (token, username, expires_at) VALUES (?,?,?)",
        (token, username, expires),
    )
    conn.commit()
    conn.close()
    return token


def validate_session(token: str) -> Optional[str]:
    if not token:
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, expires_at FROM sessions WHERE token=?", (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    username, exp = row
    if datetime.now() > datetime.fromisoformat(exp):
        delete_session(token)
        return None
    return username


def delete_session(token: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


def cleanup_sessions():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),)
    )
    conn.commit()
    conn.close()


def _cleanup_loop():
    while True:
        time.sleep(3600)
        cleanup_sessions()


threading.Thread(target=_cleanup_loop, daemon=True).start()


# ---------- User helpers ----------
def verify_user(username: str, password: str) -> bool:
    hashed = hashlib.sha256(password.encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE username=? AND password=?", (username, hashed))
    found = c.fetchone() is not None
    conn.close()
    return found


def get_user(username: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def is_admin(username: str) -> bool:
    u = get_user(username)
    return bool(u and u.get("is_admin"))


def current_user(request: Request) -> Optional[str]:
    return validate_session(request.cookies.get("session_token"))


def require_user(request: Request) -> str:
    u = current_user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u


def require_admin(request: Request) -> str:
    u = require_user(request)
    if not is_admin(u):
        raise HTTPException(status_code=403, detail="Admin required")
    return u


# ---------- Recognition proxy helper ----------
def recog(method: str, path: str, **kwargs):
    """Proxy a request to the recognition server with internal key."""
    url = f"{RECOG_BASE}{path}"
    headers = kwargs.pop("headers", {})
    headers["X-Internal-Key"] = INTERNAL_KEY
    timeout = kwargs.pop("timeout", 30)  # increased from 10 to 30 seconds
    return req_lib.request(method, url, headers=headers, timeout=timeout, **kwargs)


templates = Jinja2Templates(directory="templates")
for d in ["templates", "static", "static/css", "static/js", "static/icons"]:
    os.makedirs(d, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/camera", response_class=HTMLResponse)
async def camera_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    base = f"{request.base_url.scheme}://{request.base_url.hostname}"
    return templates.TemplateResponse(
        "camera.html",
        {
            "request": request,
            "camera_url": f"{base}:8080/api/proxy/stream",
            "camera_api": f"{base}:8000",
            "recognition_api": f"{base}:8001",
        },
    )


# ---------- Auth API ----------
@app.post("/api/login")
async def api_login(request: Request):
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    remember = data.get("remember", False)
    if not username or not password:
        return JSONResponse(
            {"success": False, "message": "Username and password required"}
        )
    if not verify_user(username, password):
        return JSONResponse({"success": False, "message": "Invalid credentials"})
    days = 30 if remember else 7
    token = create_session(username, days)
    resp = JSONResponse({"success": True, "is_admin": is_admin(username)})
    resp.set_cookie(
        "session_token", token, httponly=True, max_age=days * 86400, samesite="lax"
    )
    resp.set_cookie("username", username, max_age=days * 86400)
    return resp


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        delete_session(token)
    resp = JSONResponse({"success": True})
    resp.delete_cookie("session_token")
    resp.delete_cookie("username")
    return resp


@app.get("/api/check_admin")
async def check_admin_api(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"authenticated": False, "is_admin": False})
    return JSONResponse(
        {"authenticated": True, "is_admin": is_admin(user), "username": user}
    )


@app.post("/api/change_password")
async def change_password(request: Request):
    user = require_user(request)
    data = await request.json()
    if data.get("username") != user:
        raise HTTPException(status_code=403, detail="Unauthorized")
    if not verify_user(user, data.get("current_password", "")):
        return JSONResponse({"success": False, "message": "Current password incorrect"})
    new_hash = hashlib.sha256(data.get("new_password", "").encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET password=? WHERE username=?", (new_hash, user))
    conn.commit()
    conn.close()
    return JSONResponse({"success": True, "message": "Password changed"})


# ---------- User management API ----------
@app.get("/api/users")
async def get_users(request: Request):
    require_admin(request)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id,username,is_admin,entry_start_time,entry_end_time,created_at FROM users"
    ).fetchall()
    conn.close()
    return JSONResponse({"success": True, "users": [dict(r) for r in rows]})


@app.post("/api/users")
async def add_user(request: Request):
    require_admin(request)
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return JSONResponse(
            {"success": False, "message": "Username and password required"}
        )
    # Check not already a face
    if os.path.exists(RECOG_DB_PATH):
        conn = sqlite3.connect(RECOG_DB_PATH)
        row = conn.execute(
            "SELECT name FROM faces WHERE name=?", (username,)
        ).fetchone()
        conn.close()
        if row:
            return JSONResponse(
                {"success": False, "message": f"'{username}' already exists as a face"}
            )
    hashed = hashlib.sha256(password.encode()).hexdigest()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO users (username,password,is_admin,entry_start_time,entry_end_time) VALUES (?,?,?,?,?)",
            (
                username,
                hashed,
                data.get("isAdmin", 0),
                data.get("startTime", "00:00"),
                data.get("endTime", "23:59"),
            ),
        )
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        return JSONResponse({"success": False, "message": "Username already exists"})
    return JSONResponse({"success": True, "message": f"User {username} added"})


@app.put("/api/users/update")
async def update_user(request: Request):
    require_admin(request)
    data = await request.json()
    username = data.get("username")
    if not username:
        return JSONResponse({"success": False, "message": "Username required"})
    updates, params = [], []
    for field, col in [
        ("startTime", "entry_start_time"),
        ("endTime", "entry_end_time"),
        ("isAdmin", "is_admin"),
    ]:
        if field in data:
            updates.append(f"{col}=?")
            params.append(data[field])
    if not updates:
        return JSONResponse({"success": False, "message": "Nothing to update"})
    params.append(username)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"UPDATE users SET {','.join(updates)} WHERE username=?", params)
    conn.commit()
    conn.close()
    return JSONResponse({"success": True, "message": f"User {username} updated"})


@app.delete("/api/users")
async def delete_user(request: Request):
    require_admin(request)
    data = await request.json()
    username = data.get("username")
    if username == "admin":
        return JSONResponse({"success": False, "message": "Cannot delete admin"})
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    folder = os.path.join(DATABASE_FOLDER, username)
    if os.path.exists(folder):
        shutil.rmtree(folder)
    return JSONResponse({"success": True, "message": f"User {username} deleted"})


# ---------- Proxy endpoints (add internal key, forward to recognition server) ----------
@app.get("/api/proxy/stats")
async def proxy_stats(request: Request):
    require_user(request)
    try:
        r = recog("GET", "/api/stats")
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/proxy/logs")
async def proxy_logs(request: Request):
    require_user(request)
    params = dict(request.query_params)
    try:
        r = recog("GET", "/api/logs", params=params)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.delete("/api/proxy/logs/{log_id}")
async def proxy_delete_log(log_id: int, request: Request):
    require_admin(request)
    try:
        r = recog("DELETE", f"/api/logs/{log_id}")
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.delete("/api/proxy/clear_logs")
async def proxy_clear_logs(request: Request):
    require_admin(request)
    try:
        r = recog("DELETE", "/api/clear_recognition_logs", timeout=180)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/proxy/faces")
async def proxy_faces(request: Request):
    require_user(request)
    try:
        r = recog("GET", "/api/faces", timeout=180)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/proxy/faces")
async def proxy_create_face(request: Request):
    require_admin(request)
    data = await request.json()
    try:
        r = recog("POST", "/api/faces", json=data, timeout=180)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

@app.put("/api/proxy/faces/{name}")
async def proxy_update_face(name: str, request: Request):
    require_admin(request)
    data = await request.json()
    try:
        r = recog("PUT", f"/api/faces/{name}", json=data)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.delete("/api/proxy/faces/{name}")
async def proxy_delete_face(name: str, request: Request):
    require_admin(request)
    try:
        r = recog("DELETE", f"/api/faces/{name}", timeout=180)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.delete("/api/proxy/trained_data/{person}/{image}")
async def proxy_delete_trained_image(person: str, image: str, request: Request):
    require_admin(request)
    try:
        r = recog("DELETE", f"/api/trained_data/{person}/{image}", timeout=180)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/proxy/trained_data")
async def proxy_trained_data(request: Request):
    require_user(request)
    try:
        r = recog("GET", "/api/trained_data")
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/proxy/door_logs")
async def proxy_door_logs(request: Request):
    require_user(request)
    params = dict(request.query_params)
    try:
        r = recog("GET", "/api/door_logs", params=params)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/proxy/cache/rebuild")
async def proxy_rebuild_cache(request: Request):
    require_admin(request)
    try:
        r = recog("POST", "/api/cache/rebuild", timeout=180)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/proxy/logs/{log_id}/move_to_database")
async def proxy_move_to_db(log_id: int, request: Request):
    require_admin(request)
    data = await request.json()
    try:
        r = recog("POST", f"/api/logs/{log_id}/move_to_database", json=data, timeout=180)
        return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# ---------- Log files ----------
@app.get("/api/log_files")
async def list_log_files(request: Request):
    require_admin(request)
    files = []
    for f in os.listdir(LOG_DIR):
        if f.endswith(".log"):
            p = os.path.join(LOG_DIR, f)
            st = os.stat(p)
            files.append(
                {
                    "name": f,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                }
            )
    files.sort(key=lambda x: x["modified"], reverse=True)
    return JSONResponse({"success": True, "files": files})


@app.get("/api/log_file/{filename}")
async def get_log_file(filename: str, request: Request, lines: int = 200):
    require_admin(request)
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(LOG_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    with open(path, "r") as f:
        all_lines = f.readlines()
    return PlainTextResponse("".join(all_lines[-lines:]))


@app.post("/api/log_file/clear/{filename}")
async def clear_log_file(filename: str, request: Request):
    require_admin(request)
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(LOG_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    with open(path, "w") as f:
        f.write(f"--- Cleared at {datetime.now().isoformat()} ---\n")
    return JSONResponse({"success": True})


@app.post("/api/clear_log_files")
async def clear_all_logs(request: Request):
    require_admin(request)
    count = 0
    for f in os.listdir(LOG_DIR):
        if f.endswith(".log"):
            with open(os.path.join(LOG_DIR, f), "w") as fh:
                fh.write(f"--- Cleared at {datetime.now().isoformat()} ---\n")
            count += 1
    return JSONResponse({"success": True, "message": f"Cleared {count} log files"})


@app.get("/api/folder/stats")
async def folder_stats(request: Request):
    require_admin(request)

    def dir_stats(path):
        total_size, total_files = 0, 0
        if os.path.exists(path):
            for root, _, files in os.walk(path):
                imgs = [
                    f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png"))
                ]
                total_files += len(imgs)
                total_size += sum(os.path.getsize(os.path.join(root, f)) for f in imgs)
        return total_size, total_files

    def fmt(size):
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    rec_size, rec_files = dir_stats(RECOGNISED_FOLDER)
    unrec_size, unrec_files = dir_stats(UNRECOGNISED_FOLDER)
    db_size, db_files = dir_stats(DATABASE_FOLDER)
    db_people = (
        len(
            [
                d
                for d in os.listdir(DATABASE_FOLDER)
                if os.path.isdir(os.path.join(DATABASE_FOLDER, d))
            ]
        )
        if os.path.exists(DATABASE_FOLDER)
        else 0
    )
    rec_people = (
        len(
            [
                d
                for d in os.listdir(RECOGNISED_FOLDER)
                if os.path.isdir(os.path.join(RECOGNISED_FOLDER, d))
            ]
        )
        if os.path.exists(RECOGNISED_FOLDER)
        else 0
    )

    return JSONResponse(
        {
            "success": True,
            "stats": {
                "upload": {
                    "recognised": {
                        "size": rec_size,
                        "size_str": fmt(rec_size),
                        "files": rec_files,
                        "people": rec_people,
                    },
                    "unrecognised": {
                        "size": unrec_size,
                        "size_str": fmt(unrec_size),
                        "files": unrec_files,
                    },
                },
                "database": {
                    "size": db_size,
                    "size_str": fmt(db_size),
                    "files": db_files,
                    "people": db_people,
                },
            },
        }
    )


# ---------- Proxy image endpoints (so dashboard only needs to talk to port 8080) ----------


@app.get("/api/proxy/log_image/recognised/{name}/{filename}")
async def proxy_recognised_image(name: str, filename: str, request: Request):
    require_user(request)
    url = f"{RECOG_BASE}/api/image/recognised/{name}/{filename}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url, headers={"X-Internal-Key": INTERNAL_KEY}, timeout=5
            )
        return FastAPIResponse(
            content=r.content, media_type=r.headers.get("content-type", "image/jpeg")
        )
    except:
        return JSONResponse({"error": "Image not found"}, status_code=404)


@app.get("/api/proxy/log_image/unrecognised/{filename}")
async def proxy_unrecognised_image(filename: str, request: Request):
    require_user(request)
    url = f"{RECOG_BASE}/api/image/unrecognised/{filename}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url, headers={"X-Internal-Key": INTERNAL_KEY}, timeout=5
            )
        return FastAPIResponse(
            content=r.content, media_type=r.headers.get("content-type", "image/jpeg")
        )
    except:
        return JSONResponse({"error": "Image not found"}, status_code=404)


@app.get("/api/proxy/trained_image/{person}/{image}")
async def proxy_trained_image(person: str, image: str, request: Request):
    require_user(request)
    url = f"{RECOG_BASE}/api/trained_image/{person}/{image}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url, headers={"X-Internal-Key": INTERNAL_KEY}, timeout=5
            )
        return FastAPIResponse(
            content=r.content, media_type=r.headers.get("content-type", "image/jpeg")
        )
    except:
        return JSONResponse({"error": "Image not found"}, status_code=404)
    

@app.post("/api/proxy/door")
async def proxy_door(request: Request):
    # Require authenticated user (any logged-in user)
    user = require_user(request)
    try:
        data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
        # Forward to camera server with internal key
        url = f"{CAMERA_BASE}/api/open_door"
        headers = {"X-Internal-Key": INTERNAL_KEY}
        resp = req_lib.post(url, json=data, headers=headers, timeout=5)
        return JSONResponse(resp.json(), status_code=resp.status_code)
    except req_lib.exceptions.Timeout:
        return JSONResponse({"error": "Door API timeout"}, status_code=504)
    except Exception as e:
        logger.error(f"Door proxy error: {e}")
        return JSONResponse({"error": str(e)}, status_code=502)

@app.get("/api/proxy/face_detected")
async def proxy_face_detected(request: Request):
    require_user(request)
    try:
        url = f"{CAMERA_BASE}/api/face_detected"
        headers = {"X-Internal-Key": INTERNAL_KEY}
        resp = req_lib.get(url, headers=headers, timeout=5)
        return JSONResponse(resp.json(), status_code=resp.status_code)
    except req_lib.exceptions.Timeout:
        return JSONResponse({"error": "Camera server timeout"}, status_code=504)
    except Exception as e:
        logger.error(f"Face detection proxy error: {e}")
        return JSONResponse({"error": str(e)}, status_code=502)

@app.get("/api/proxy/stream")
async def proxy_stream(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    # Stream proxy — forward MJPEG from camera server
    async def stream_gen():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{Config.CAMERA_BASE}/video_feed",
                                     headers={"X-Internal-Key": INTERNAL_KEY},
                                     timeout=None) as r:
                async for chunk in r.aiter_bytes(1024):
                    yield chunk
    return StreamingResponse(stream_gen(),
        media_type="multipart/x-mixed-replace;boundary=frame")


@app.get("/api/settings")
async def get_settings_api(request: Request):
    require_admin(request)
    from settings_manager import DEFAULTS
    SETTINGS_META = {
        "door_url":              {"label": "Door Trigger URL",            "type": "text",     "group": "Door"},
        "door_auth_key":         {"label": "Door Auth Key",               "type": "password", "group": "Door"},
        "door_use_auth":         {"label": "Use Auth Key",                "type": "bool",     "group": "Door"},
        "door_auto_open":        {"label": "Auto Open Door",              "type": "bool",     "group": "Door"},
        "door_success_delay":    {"label": "Delay After Success (s)",     "type": "float",    "group": "Door",          "min": 0,   "max": 30},
        "door_error_delay":      {"label": "Delay After Error (s)",       "type": "float",    "group": "Door",          "min": 0,   "max": 30},
        "recognition_threshold": {"label": "Recognition Threshold (%)",   "type": "int",      "group": "Recognition",   "min": 1,   "max": 100},
        "margin_threshold":      {"label": "Margin Threshold (%)",        "type": "float",    "group": "Recognition",   "min": 0,   "max": 50},
        "yunet_score_threshold": {"label": "YuNet Score Threshold",       "type": "float",    "group": "Detection",     "min": 0.1, "max": 1.0},
        "yunet_nms_threshold":   {"label": "YuNet NMS Threshold",         "type": "float",    "group": "Detection",     "min": 0.1, "max": 1.0},
        "send_interval":         {"label": "Send Interval (s)",           "type": "float",    "group": "Camera",        "min": 0.5, "max": 10},
        "frame_quality":         {"label": "Stream JPEG Quality",         "type": "int",      "group": "Camera",        "min": 10,  "max": 100},
        "camera_rotatation_angle":{"label": "Camera Rotation Angle°",     "type": "int",      "group": "Camera",        "min": 0,   "max": 359},
        "camera_mirror"         :{"label": "Camera Mirror",               "type": "bool",     "group": "Camera"},
        "crop_region_enabled":   {"label": "Enable Crop Region",          "type": "bool",     "group": "Crop Region"},
        "crop_x_start":          {"label": "Crop X Start (px)",           "type": "int",      "group": "Crop Region",   "min": 0,   "max": 640},
        "crop_x_end":            {"label": "Crop X End (px)",             "type": "int",      "group": "Crop Region",   "min": 0,   "max": 640},
        "crop_y_start":          {"label": "Crop Y Start (px)",           "type": "int",      "group": "Crop Region",   "min": 0,   "max": 480},
        "crop_y_end":            {"label": "Crop Y End (px)",             "type": "int",      "group": "Crop Region",   "min": 0,   "max": 480},
    }
    s = get_settings()
    current = s.all()
    result = {}
    for key, meta in SETTINGS_META.items():
        result[key] = {**meta, "value": current.get(key), "default": DEFAULTS.get(key)}
    return JSONResponse({"success": True, "settings": result})



@app.put("/api/settings")
async def update_settings_api(request: Request):
    require_admin(request)
    data = await request.json()
    updates = data.get("updates", {})
    if not updates:
        return JSONResponse({"success": False, "message": "No updates provided"})
    invalid = [k for k in updates if k not in DEFAULTS]
    if invalid:
        return JSONResponse({"success": False, "message": f"Unknown keys: {invalid}"})
    ok = get_settings().set_many(updates)
    if ok:
        logger.info(f"Settings updated: {list(updates.keys())}")
        return JSONResponse({"success": True, "message": "Settings saved"})
    return JSONResponse({"success": False, "message": "DB error"}, status_code=500)

@app.get("/api/settings/auto_open")
async def get_auto_open_settings_api(request: Request):
    require_admin(request)
    s = get_settings()
    value = s.get("door_auto_open", True)
    return JSONResponse({"success": True, "message": value})

@app.put("/api/settings/auto_open")
async def update_auto_open_settings_api(request: Request):
    require_admin(request)
    data = await request.json()
    value = data.get("value", True)
    ok = get_settings().set("door_auto_open", value)
    if ok:
        logger.info(f"Door setting updated: {value}")
        return JSONResponse({"success": True, "message": "Door setting saved"})
    return JSONResponse({"success": False, "message": "DB error"}, status_code=500)



@app.get("/api/internal/settings")
async def internal_settings_api(request: Request):
    # Protected by existing internal key middleware
    return JSONResponse({"success": True, "settings": get_settings().all()})



@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if os.path.exists("static/react"):
    app.mount("/", StaticFiles(directory="static/react", html=True), name="react")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
