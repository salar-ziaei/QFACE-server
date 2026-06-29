from fastapi import FastAPI, File, UploadFile, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import cv2
import numpy as np
import datetime
import os
import shutil
import sqlite3
from typing import Optional, List
import logging
from logging.handlers import RotatingFileHandler
import sys
import pickle
import threading
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import Config
from settings_manager import init_settings, get_settings

# ---------- Logging ----------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(LOG_DIR, "recognition.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="QFACE - Recognition Server")

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

# ---------- Folders ----------
UNRECOGNISED_FOLDER = "upload/unrecognised"
RECOGNISED_FOLDER = "upload/recognised"
DATABASE_FOLDER = "database"
for d in [UNRECOGNISED_FOLDER, RECOGNISED_FOLDER, LOG_DIR, DATABASE_FOLDER]:
    os.makedirs(d, exist_ok=True)

DB_PATH = os.path.join(LOG_DIR, "recognition.db")

# ---------- Database ----------
def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS recognition_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        date TEXT NOT NULL,
        filename TEXT NOT NULL,
        prediction TEXT,
        confidence REAL,
        is_recognised INTEGER NOT NULL,
        saved_in TEXT NOT NULL,
        image_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS faces (
        name TEXT PRIMARY KEY,
        entry_start_time TEXT DEFAULT '00:00',
        entry_end_time TEXT DEFAULT '23:59',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS door_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        person TEXT,
        action TEXT,
        result TEXT,
        confidence REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_rl_timestamp ON recognition_logs(timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_rl_prediction ON recognition_logs(prediction)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_rl_recognised ON recognition_logs(is_recognised)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_dl_timestamp ON door_logs(timestamp)')
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_database()
DB_PATH_SETTINGS = DB_PATH  # same DB
settings = init_settings(DB_PATH_SETTINGS)
settings.start_auto_refresh(30)

# ---------- SFace ----------
SFACE_MODEL_PATH = "models/face_recognition_sface_2021dec.onnx"
sface_recognizer = None
use_sface = False

if os.path.exists(SFACE_MODEL_PATH):
    try:
        sface_recognizer = cv2.FaceRecognizerSF.create(SFACE_MODEL_PATH, "")
        if sface_recognizer:
            use_sface = True
            logger.info("SFace loaded successfully")
    except Exception as e:
        logger.warning(f"SFace load error: {e}, falling back to ORB")
else:
    logger.warning(f"SFace model not found at {SFACE_MODEL_PATH}")

orb = cv2.ORB.create(nfeatures=1000)

# ---------- In-memory face cache ----------
# Structure:
#   sface mode:  { name: np.ndarray shape (N, 128) }  — stacked embeddings matrix
#   orb mode:    { name: [descriptor, ...] }
_face_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_PATH = os.path.join(LOG_DIR, "face_cache.pkl")

def _load_cache_from_disk() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.error(f"Cache load error: {e}")
    return {}

def _save_cache_to_disk(cache: dict):
    try:
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)
    except Exception as e:
        logger.error(f"Cache save error: {e}")

def _build_cache() -> dict:
    cache = {}
    if not os.path.exists(DATABASE_FOLDER):
        return cache
    for person in os.listdir(DATABASE_FOLDER):
        person_path = os.path.join(DATABASE_FOLDER, person)
        if not os.path.isdir(person_path):
            continue
        entries = []
        for img_file in os.listdir(person_path):
            if not img_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            img_path = os.path.join(person_path, img_file)
            if use_sface:
                emb = _compute_embedding(img_path)
                if emb is not None:
                    entries.append(emb)
            else:
                des = _compute_orb(img_path)
                if des is not None:
                    entries.append(des)
        if entries:
            if use_sface:
                # Stack into matrix for fast batch cosine similarity
                cache[person] = np.stack(entries, axis=0)  # shape (N, 128)
            else:
                cache[person] = entries
    _save_cache_to_disk(cache)
    logger.info(f"Cache built: {len(cache)} people ({'SFace' if use_sface else 'ORB'})")
    return cache

def rebuild_cache():
    global _face_cache
    new_cache = _build_cache()
    with _cache_lock:
        _face_cache = new_cache

def get_cache() -> dict:
    with _cache_lock:
        return _face_cache

# ---------- Load cache into memory at startup ----------
@app.on_event("startup")
async def startup():
    global _face_cache
    loaded = _load_cache_from_disk()
    if loaded:
        _face_cache = loaded
        logger.info(f"Cache loaded from disk: {len(_face_cache)} people")
    else:
        logger.info("No cache on disk, building...")
        _face_cache = _build_cache()

# ---------- Feature extraction ----------
def _compute_embedding(image_path: str) -> Optional[np.ndarray]:
    img = cv2.imread(image_path)
    if img is None:
        return None
    face = cv2.resize(img, (112, 112))
    try:
        emb = sface_recognizer.feature(face)
        return emb.flatten().astype(np.float32)
    except Exception as e:
        logger.error(f"SFace embedding error: {e}")
        return None

def _compute_embedding_from_array(img: np.ndarray) -> Optional[np.ndarray]:
    if img is None:
        return None
    face = cv2.resize(img, (112, 112))
    try:
        emb = sface_recognizer.feature(face)
        return emb.flatten().astype(np.float32)
    except Exception as e:
        logger.error(f"SFace embedding error: {e}")
        return None

def _compute_orb(image_path: str):
    img = cv2.imread(image_path)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, des = orb.detectAndCompute(gray, None)
    return des

# ---------- Recognition: batched cosine similarity ----------
def _cosine_similarity_batch(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    query:  shape (D,)
    matrix: shape (N, D)
    returns: shape (N,) similarities in [0, 100]
    """
    q_norm = query / (np.linalg.norm(query) + 1e-8)
    m_norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8
    m_normalized = matrix / m_norms
    sims = m_normalized @ q_norm  # shape (N,)
    sims = np.clip(sims, -1.0, 1.0)
    return (sims + 1.0) / 2.0 * 100.0

def _compare_orb(query_des, db_des) -> float:
    if query_des is None or db_des is None:
        return 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(query_des, db_des)
    if not matches:
        return 0.0
    good = [m for m in matches if m.distance < 50]
    return min((len(good) / max(len(query_des), 1)) * 100, 100.0)

def load_and_predict(img: np.ndarray, threshold=None):
    s = get_settings()
    if threshold is None:
        threshold = s.get("recognition_threshold", Config.RECOGNITION_THRESHOLD)
    try:
        cache = get_cache()
        if not cache:
            logger.warning("Cache empty, rebuilding...")
            rebuild_cache()
            cache = get_cache()
            if not cache:
                return "Unknown", 0, False

        if use_sface:
            query_emb = _compute_embedding_from_array(img)
            if query_emb is None:
                return "Unknown", 0, False
        else:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, query_des = orb.detectAndCompute(gray, None)
            if query_des is None:
                return "Unknown", 0, False

        best_match = "Unknown"
        best_score = 0.0
        second_best = 0.0

        for person, data in cache.items():
            if use_sface:
                # Batched: one matrix multiply for all embeddings of this person
                scores = _cosine_similarity_batch(query_emb, data)
                person_best = float(np.max(scores))
            else:
                person_best = max(_compare_orb(query_des, d) for d in data)

            if person_best > best_score:
                second_best = best_score
                best_score = person_best
                best_match = person
            elif person_best > second_best:
                second_best = person_best

        margin = best_score - second_best
        margin_threshold = s.get("margin_threshold", 5.0)

        if best_score >= threshold and margin >= margin_threshold:
            face_info = get_face(best_match)
            if face_info:
                now = datetime.datetime.now().time()
                start = datetime.datetime.strptime(face_info['entry_start_time'], '%H:%M').time()
                end = datetime.datetime.strptime(face_info['entry_end_time'], '%H:%M').time()
                if start <= end:
                    allowed = start <= now <= end
                else:
                    allowed = now >= start or now <= end
            else:
                allowed = True
            logger.info(f"Match: {best_match} score={best_score:.1f}% margin={margin:.1f}% allowed={allowed}")
            return best_match, best_score, allowed
        else:
            if best_score >= threshold:
                logger.info(f"Ambiguous: score={best_score:.1f}% margin={margin:.1f}% < 5%")
            return "Unknown", 0.0, False
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        return "Unknown", 0.0, False

# ---------- DB helpers ----------
def log_recognition_db(filename, prediction, confidence, is_recognised, saved_in, date_str, image_path):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''INSERT INTO recognition_logs
            (timestamp, date, filename, prediction, confidence, is_recognised, saved_in, image_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (datetime.datetime.now().isoformat(), date_str, filename,
             prediction, float(confidence or 0), 1 if is_recognised else 0, saved_in, image_path))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Log error: {e}")

def get_logs_from_db(limit=50, offset=0, is_recognised=None, search="", last_id=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        where = []
        params = []
        if is_recognised is not None:
            where.append("is_recognised = ?")
            params.append(1 if is_recognised else 0)
        if search:
            where.append("(prediction LIKE ? OR filename LIKE ? OR date LIKE ?)")
            p = f"%{search}%"
            params.extend([p, p, p])
        if last_id is not None:
            where.append("id > ?")
            params.append(last_id)
        q = "SELECT * FROM recognition_logs"
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        c.execute(q, params)
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['is_recognised'] = bool(r['is_recognised'])
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Log read error: {e}")
        return []

def get_stats_from_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM recognition_logs")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM recognition_logs WHERE is_recognised = 1")
        recognised = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM recognition_logs WHERE is_recognised = 0")
        unrecognised = c.fetchone()[0]
        c.execute("SELECT DISTINCT prediction FROM recognition_logs WHERE is_recognised=1 AND prediction NOT IN ('Unknown','Model Not Ready') AND prediction IS NOT NULL")
        unique_people = [r[0] for r in c.fetchall()]
        conn.close()
        return {"total": total, "recognised": recognised, "unrecognised": unrecognised,
                "unique_people": len(unique_people), "people_list": unique_people}
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {"total": 0, "recognised": 0, "unrecognised": 0, "unique_people": 0, "people_list": []}

def get_face(name):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM faces WHERE name = ?', (name,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_faces():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM faces ORDER BY name')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_face(name, start='00:00', end='23:59'):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT INTO faces (name, entry_start_time, entry_end_time) VALUES (?, ?, ?)', (name, start, end))
    conn.commit()
    conn.close()
    os.makedirs(os.path.join(DATABASE_FOLDER, name), exist_ok=True)

def update_face_time(name, start, end):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('UPDATE faces SET entry_start_time=?, entry_end_time=? WHERE name=?', (start, end, name))
    conn.commit()
    conn.close()

def delete_face(name):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('DELETE FROM faces WHERE name=?', (name,))
    conn.commit()
    conn.close()
    folder = os.path.join(DATABASE_FOLDER, name)
    if os.path.exists(folder):
        shutil.rmtree(folder)

# ---------- Endpoints ----------
@app.post("/upload-cropped")
async def upload_cropped(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return JSONResponse(status_code=400, content={"error": "Invalid image"})

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"r-{date_str}.jpg"

        prediction, confidence, allowed = load_and_predict(img)

        if prediction and prediction not in ("Unknown", "Model Not Ready"):
            folder = os.path.join(RECOGNISED_FOLDER, prediction)
            os.makedirs(folder, exist_ok=True)
            save_path = os.path.join(folder, filename)
            is_recognised = True
            saved_in = f"recognised/{prediction}"
        else:
            save_path = os.path.join(UNRECOGNISED_FOLDER, filename)
            is_recognised = False
            saved_in = "unrecognised"

        cv2.imwrite(save_path, img)
        log_recognition_db(filename, prediction, confidence, is_recognised, saved_in, date_str, save_path)

        return {
            "message": f"Recognised: {prediction}" if is_recognised else "Not recognised",
            "filename": filename,
            "image": os.path.join(saved_in, filename),
            "prediction": prediction,
            "confidence": float(confidence),
            "is_recognised": is_recognised,
            "date": date_str,
            "access_allowed": allowed
        }
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/logs")
async def get_logs_api(
    tab: str = "all",
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    last_id: Optional[int] = None
):
    if tab == "stats":
        return JSONResponse({"success": True, "stats": get_stats_from_db()})

    is_recognised = None
    if tab == "recognised":
        is_recognised = True
    elif tab == "unrecognised":
        is_recognised = False

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    where = []
    params = []
    if is_recognised is not None:
        where.append("is_recognised = ?")
        params.append(1 if is_recognised else 0)
    if search:
        where.append("(prediction LIKE ? OR filename LIKE ? OR date LIKE ?)")
        p = f"%{search}%"
        params.extend([p, p, p])
    w = (" WHERE " + " AND ".join(where)) if where else ""
    c.execute(f"SELECT COUNT(*) FROM recognition_logs{w}", params)
    total = c.fetchone()[0]
    conn.close()

    logs = get_logs_from_db(limit=limit, offset=offset, is_recognised=is_recognised,
                             search=search, last_id=last_id)
    stats = get_stats_from_db()
    pages = (total + limit - 1) // limit if limit > 0 else 1

    return JSONResponse({
        "success": True, "logs": logs, "stats": stats,
        "total": total, "limit": limit, "offset": offset, "pages": pages
    })

@app.get("/api/stats")
async def get_stats_api():
    return JSONResponse(get_stats_from_db())

@app.delete("/api/logs/{log_id}")
async def delete_log(log_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT image_path FROM recognition_logs WHERE id=?", (log_id,))
        row = c.fetchone()
        if row and row[0] and os.path.exists(row[0]):
            try:
                os.remove(row[0])
                parent = os.path.dirname(row[0])
                if parent not in (RECOGNISED_FOLDER, UNRECOGNISED_FOLDER):
                    if os.path.exists(parent) and not os.listdir(parent):
                        os.rmdir(parent)
            except:
                pass
        c.execute("DELETE FROM recognition_logs WHERE id=?", (log_id,))
        conn.commit()
        conn.close()
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@app.delete("/api/clear_recognition_logs")
async def clear_recognition_logs():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT image_path FROM recognition_logs")
        rows = c.fetchall()
        deleted = 0
        for row in rows:
            p = row[0]
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                    deleted += 1
                    parent = os.path.dirname(p)
                    if parent not in (RECOGNISED_FOLDER, UNRECOGNISED_FOLDER):
                        if os.path.exists(parent) and not os.listdir(parent):
                            os.rmdir(parent)
                except:
                    pass
        c.execute("DELETE FROM recognition_logs")
        c.execute("DELETE FROM door_logs")
        conn.commit()
        conn.close()
        return JSONResponse({"success": True, "message": f"Cleared logs, deleted {deleted} images"})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@app.get("/api/image/recognised/{name}/{filename}")
async def get_recognised_image(name: str, filename: str):
    p = os.path.join(RECOGNISED_FOLDER, name, filename)
    if os.path.exists(p):
        return FileResponse(p)
    return JSONResponse({"error": "Not found"}, status_code=404)

@app.get("/api/image/unrecognised/{filename}")
async def get_unrecognised_image(filename: str):
    p = os.path.join(UNRECOGNISED_FOLDER, filename)
    if os.path.exists(p):
        return FileResponse(p)
    return JSONResponse({"error": "Not found"}, status_code=404)

@app.post("/api/logs/{log_id}/move_to_database")
async def move_log_to_database(log_id: int, request: Request):
    try:
        data = await request.json()
        custom_name = data.get('name')
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM recognition_logs WHERE id=?', (log_id,))
        log = c.fetchone()
        conn.close()
        if not log:
            return JSONResponse({"success": False, "message": "Log not found"}, status_code=404)
        log = dict(log)
        dest_name = custom_name or (log['prediction'] if log['is_recognised'] and log['prediction'] not in ('Unknown', None) else None)
        if not dest_name:
            return JSONResponse({"success": False, "message": "Cannot determine name"}, status_code=400)
        source = log['image_path']
        if not source or not os.path.exists(source):
            return JSONResponse({"success": False, "message": "Source image not found"}, status_code=404)
        dest_folder = os.path.join(DATABASE_FOLDER, dest_name)
        os.makedirs(dest_folder, exist_ok=True)
        shutil.copy2(source, os.path.join(dest_folder, log['filename']))
        rebuild_cache()
        return JSONResponse({"success": True, "message": f"Moved to database as: {dest_name}"})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

# ---------- Face API ----------
@app.get("/api/faces")
async def list_faces():
    faces = get_all_faces()
    for f in faces:
        folder = os.path.join(DATABASE_FOLDER, f['name'])
        f['image_count'] = len([x for x in os.listdir(folder) if x.endswith(('.jpg', '.jpeg', '.png'))]) if os.path.exists(folder) else 0
    return JSONResponse({"success": True, "faces": faces})

@app.post("/api/faces")
async def create_face(request: Request):
    data = await request.json()
    name = data.get('name')
    start = data.get('start_time', '00:00')
    end = data.get('end_time', '23:59')
    if not name:
        return JSONResponse({"success": False, "message": "Name required"}, status_code=400)
    if get_face(name):
        return JSONResponse({"success": False, "message": "Face already exists"}, status_code=400)
    users_db = os.path.join(LOG_DIR, "users.db")
    if os.path.exists(users_db):
        c = sqlite3.connect(users_db)
        row = c.execute('SELECT username FROM users WHERE username=?', (name,)).fetchone()
        c.close()
        if row:
            return JSONResponse({"success": False, "message": f"'{name}' is already a user"}, status_code=400)
    add_face(name, start, end)
    return JSONResponse({"success": True, "message": f"Face {name} created"})

@app.put("/api/faces/{name}")
async def update_face(name: str, request: Request):
    data = await request.json()
    start = data.get('start_time')
    end = data.get('end_time')
    if not start or not end:
        return JSONResponse({"success": False, "message": "Both times required"}, status_code=400)
    if not get_face(name):
        return JSONResponse({"success": False, "message": "Face not found"}, status_code=404)
    update_face_time(name, start, end)
    return JSONResponse({"success": True, "message": f"Updated {name}"})

@app.delete("/api/faces/{name}")
async def remove_face(name: str):
    if not get_face(name):
        return JSONResponse({"success": False, "message": "Face not found"}, status_code=404)
    delete_face(name)
    with _cache_lock:
        _face_cache.pop(name, None)
        snap = dict(_face_cache)
    _save_cache_to_disk(snap)
    return JSONResponse({"success": True, "message": f"Face {name} deleted"})

@app.post("/api/faces/{name}/train")
async def train_face(name: str, images: List[UploadFile] = File(...)):
    if not get_face(name):
        return JSONResponse({"success": False, "message": "Face not found"}, status_code=404)
    folder = os.path.join(DATABASE_FOLDER, name)
    os.makedirs(folder, exist_ok=True)
    saved = 0
    for img in images:
        if not img.filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            continue
        contents = await img.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is not None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            cv2.imwrite(os.path.join(folder, f"{ts}_{img.filename}"), frame)
            saved += 1
    rebuild_cache()
    return JSONResponse({"success": True, "message": f"Saved {saved} images for {name}"})

@app.get("/api/faces/{name}/images")
async def get_face_images(name: str):
    if not get_face(name):
        return JSONResponse({"success": False, "message": "Face not found"}, status_code=404)
    folder = os.path.join(DATABASE_FOLDER, name)
    images = [f for f in os.listdir(folder) if f.endswith(('.jpg', '.jpeg', '.png'))] if os.path.exists(folder) else []
    return JSONResponse({"success": True, "images": images})

# ---------- Trained data management ----------
@app.get("/api/trained_data")
async def list_trained_data():
    data = []
    if os.path.exists(DATABASE_FOLDER):
        for person in os.listdir(DATABASE_FOLDER):
            pp = os.path.join(DATABASE_FOLDER, person)
            if os.path.isdir(pp):
                imgs = [f for f in os.listdir(pp) if f.endswith(('.jpg', '.jpeg', '.png'))]
                data.append({"name": person, "image_count": len(imgs), "images": imgs})
    return JSONResponse({"success": True, "data": data})

@app.delete("/api/trained_data/{person}/{image}")
async def delete_trained_image(person: str, image: str):
    path = os.path.join(DATABASE_FOLDER, person, image)
    if not os.path.exists(path):
        return JSONResponse({"success": False, "message": "Image not found"}, status_code=404)
    os.remove(path)
    rebuild_cache()
    return JSONResponse({"success": True})

@app.get("/api/trained_image/{person}/{image}")
async def get_trained_image(person: str, image: str):
    p = os.path.join(DATABASE_FOLDER, person, image)
    if os.path.exists(p):
        return FileResponse(p)
    return JSONResponse({"error": "Not found"}, status_code=404)

# ---------- Door logs ----------
@app.post("/api/door_log")
async def add_door_log(request: Request):
    try:
        data = await request.json()
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''INSERT INTO door_logs (timestamp, person, action, result, confidence)
            VALUES (?, ?, ?, ?, ?)''',
            (datetime.datetime.now().isoformat(), data.get('person', 'Unknown'),
             data.get('action', 'door_open'), data.get('result', 'success'), data.get('confidence', 0.0)))
        conn.commit()
        conn.close()
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@app.get("/api/door_logs")
async def get_door_logs(page: int = 1, limit: int = 50, search: str = ""):
    offset = (page - 1) * limit
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        where = ""
        params = []
        if search:
            where = "WHERE person LIKE ? OR action LIKE ? OR result LIKE ?"
            p = f"%{search}%"
            params = [p, p, p]
        c.execute(f"SELECT COUNT(*) FROM door_logs {where}", params)
        total = c.fetchone()[0]
        c.execute(f"SELECT * FROM door_logs {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?", params + [limit, offset])
        logs = [dict(r) for r in c.fetchall()]
        conn.close()
        return JSONResponse({"success": True, "logs": logs, "total": total, "page": page,
                             "limit": limit, "pages": (total + limit - 1) // limit})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

# ---------- Cache endpoints ----------
@app.post("/api/cache/rebuild")
async def rebuild_cache_endpoint():
    rebuild_cache()
    return JSONResponse({"success": True, "message": "Cache rebuilt"})

@app.delete("/api/cache/clear")
async def clear_cache_endpoint():
    global _face_cache
    with _cache_lock:
        _face_cache = {}
    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)
    return JSONResponse({"success": True, "message": "Cache cleared"})

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.datetime.now().isoformat(),
            "cache_size": len(get_cache()), "use_sface": use_sface}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
