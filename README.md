<div align="center">

# QFACE Server

### Enterprise Face Recognition Backend

High-performance face recognition server built with **FastAPI**, **InsightFace**, and **OpenCV** for real-time identity recognition, camera management, and AI-powered automation.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)]()
[![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)]()
[![ONNX Runtime](https://img.shields.io/badge/ONNX_Runtime-005CED?logo=onnx&logoColor=white)]()
[![License](https://img.shields.io/badge/License-AGPLv3-red)]()

<img src="docs/dashboard.png" width="100%">

**QFACE Server powers the entire QFACE ecosystem by providing face recognition, camera communication, user management, REST APIs, and real-time WebSocket services.**

</div>

---

# Features

## AI Face Recognition

- Real-time face recognition
- Face enrollment
- Face embedding generation
- Face verification
- Unknown face detection
- Confidence scoring
- High-speed recognition pipeline

## Camera Management

- USB Cameras
- IP Cameras
- RTSP Streams
- Multiple camera support
- Live frame processing
- Camera configuration
- Camera status monitoring

## API

- RESTful API
- OpenAPI / Swagger documentation
- JWT Authentication
- JSON responses
- Versioned endpoints
- WebSocket communication

## Administration

- User management
- Settings management
- Role-based permissions
- Recognition history
- System configuration
- Device management

## Performance

- Multi-threaded processing
- ONNX Runtime acceleration
- CPU support
- GPU support
- Optimized embedding search
- Low-latency recognition

---

# Architecture

```
                   Dashboard
                       │
             REST API / WebSocket
                       │
                FastAPI Application
                       │
        ┌──────────────┼──────────────┐
        │              │              │
 Authentication   Recognition      Settings
        │              │              │
        └──────────────┼──────────────┘
                       │
                 Database Layer
                       │
             Face Embeddings Storage
                       │
             Connected Camera Clients
```

---

# Technology Stack

| Category | Technology |
|----------|------------|
| Language | Python |
| Framework | FastAPI |
| AI | InsightFace |
| Computer Vision | OpenCV |
| Inference | ONNX Runtime |
| ORM | SQLAlchemy |
| Authentication | JWT |
| Communication | REST + WebSocket |
| Data Validation | Pydantic |

---

# Project Structure

```
QFACE-server
│
├── api/
├── auth/
├── camera/
├── database/
├── models/
├── recognition/
├── routers/
├── schemas/
├── services/
├── settings/
├── utils/
├── websocket/
├── static/
├── logs/
└── main.py
```

---

# Installation

## Clone

```bash
git clone https://github.com/salar-ziaei/QFACE-server

cd QFACE-server
```

## Create Virtual Environment

### Windows

```bash
python -m venv .venv

.venv\Scripts\activate
```

### Linux

```bash
python3 -m venv .venv

source .venv/bin/activate
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Configuration

Configure the server according to your deployment.

Typical settings include:

- Database connection
- Recognition model
- Camera settings
- Authentication
- Host
- Port
- Logging
- Storage paths

---

# Running the Server

```bash
python main.py
```

or

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

# API Overview

| Method | Endpoint | Description |
|---------|----------|-------------|
| GET | `/` | Server status |
| POST | `/login` | Authenticate |
| GET | `/users` | List users |
| POST | `/users` | Create user |
| GET | `/cameras` | Camera list |
| POST | `/cameras` | Register camera |
| GET | `/persons` | List persons |
| POST | `/persons` | Enroll person |
| DELETE | `/persons/{id}` | Delete person |
| GET | `/settings` | System settings |

---

# Example Request

```http
POST /persons
```

```json
{
    "name":"John Doe",
    "department":"Engineering"
}
```

Response

```json
{
    "success":true,
    "id":25
}
```

---

# WebSocket

Real-time events include:

- Face recognized
- Camera connected
- Camera disconnected
- Person added
- Person removed
- Recognition alerts
- System notifications

---

# Recognition Pipeline

```
Camera Frame

      │

Face Detection

      │

Alignment

      │

Embedding Generation

      │

Similarity Search

      │

Recognition Result

      │

Database Logging

      │

Dashboard Notification
```

---

# Security

- JWT Authentication
- Password hashing
- Role-based authorization
- Secure API endpoints
- Input validation
- Audit logging
- CORS support

---

# Logging

The server maintains logs for:

- Recognition events
- Authentication
- API requests
- Camera connections
- Errors
- System events

---

# Performance

Designed for production deployments.

Supports:

- Multi-camera installations
- Thousands of enrolled identities
- Low-latency recognition
- Parallel processing
- GPU acceleration (when available)

---

# Integration

QFACE Server communicates with:

| Component | Purpose |
|-----------|---------|
| QFACE Dashboard | Administration |
| QFACE Client | Camera communication |
| REST API | Third-party integrations |
| WebSocket | Live updates |

---

# Screenshots

## Dashboard

![](docs/dashboard.png)

---

## Recognition

![](docs/recognition.png)

---

## Person Management

![](docs/persons.png)

---

## Camera Management

![](docs/cameras.png)

---

## System Logs

![](docs/logs.png)

---

# Roadmap

- [x] Face Recognition
- [x] REST API
- [x] WebSocket Support
- [x] Camera Management
- [x] User Management
- [x] Recognition History
- [ ] Docker Images
- [ ] Kubernetes Support
- [ ] Distributed Recognition
- [ ] Face Liveness Detection
- [ ] Plugin System
- [ ] Analytics Dashboard

---

# Contributing

Contributions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Commit your changes.
4. Push the branch.
5. Open a Pull Request.

---

# License

Licensed under the **GNU Affero General Public License v3.0 (AGPLv3).**

Commercial licenses are available for organizations that require proprietary use without AGPL obligations.

---

<div align="center">

### Part of the QFACE Ecosystem

⭐ If you find this project useful, consider giving it a star.

</div>
