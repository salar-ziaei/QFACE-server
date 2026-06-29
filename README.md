
---

## 📄 `QFACE-server/README.md`

```markdown
# QFACE Server – Backend for Face Recognition

QFACE Server is the backend of the QFACE system, consisting of three FastAPI services:

- **Camera Server** (`port 8000`) – streams video, detects faces (YuNet), and triggers door actions.
- **Recognition Server** (`port 8001`) – performs face recognition (SFace/ORB), logs recognitions, and manages face databases.
- **Main Server** (`port 8080`) – serves the dashboard UI, handles user authentication, and proxies API calls with internal API keys.

All services communicate via an internal API key for security.

## Features

- **Face detection** using YuNet (ONNX) – accurate and fast on CPU.
- **Face recognition** using SFace (with ORB fallback) – batched cosine similarity for performance.
- **Embedding caching** – face descriptors are cached to disk to reduce recomputation.
- **Dynamic settings** – adjust crop region, rotation, mirroring, and auto‑open at runtime via `/api/settings`.
- **Door logs** – every door trigger is logged in SQLite.
- **User management** – login sessions, admin roles, and password change.
- **Internal API key** – secure communication between the three servers.
- **Proxy endpoints** – the main server forwards all recognition/door requests with the internal key.

## Requirements

- Python 3.10+
- OpenCV 4.8.1+ (with contrib modules)
- Other dependencies listed in `requirements.txt`

## Installation

```bash
git clone https://github.com/salar-ziaei/QFACE-server.git
cd QFACE-server
python -m venv venv
source venv/bin/activate   # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
Configuration
Create a .env file (or set environment variables) with the following:

env
# Internal API key (must be the same for all servers)
QFACE_INTERNAL_KEY=your-strong-secret-key

# Door control
DOOR_API_URL=http://192.168.1.6/trigger
DOOR_API_KEY=your-door-secret
USE_DOOR_AUTH=false

# Recognition threshold
RECOGNITION_THRESHOLD=80

# Camera rotation
CAMERA_ROTATION=0
Alternatively, copy config.py and adjust default values.

Running the Servers
Development (individual processes)
bash
# Terminal 1 – Camera Server
python camera_server.py

# Terminal 2 – Recognition Server
python recognition_server.py

# Terminal 3 – Main Server
python main_server.py
Production (systemd)
Each service has a corresponding systemd unit file (qface-camera.service, qface-recognition.service, qface-dashboard.service). Enable and start them:

bash
sudo systemctl enable qface-camera qface-recognition qface-dashboard
sudo systemctl start qface-camera qface-recognition qface-dashboard
API Overview
Endpoint (Main Server)	Description
/api/login	User login (session cookie)
/api/users	CRUD for users (admin only)
/api/proxy/faces	List/add/delete faces
/api/proxy/logs	Fetch recognition logs
/api/proxy/door_logs	Fetch door logs
/api/proxy/trained_data	Manage training images
/api/proxy/door	Trigger door manually
Full API documentation is available at /docs on each server (e.g., http://localhost:8080/docs).

License
This project is licensed under the MIT License – see the LICENSE file for details.