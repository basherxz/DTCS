# AI Market

# 🧠 AI Market – Distributed AI Task Network

A lightweight experimental framework for coordinating and verifying distributed AI inference jobs across multiple worker nodes.  
Built with **FastAPI**, **SQLModel**, and **Hugging Face Transformers** — inspired by decentralized AI compute networks like Tensora and Bittensor.

---

## 🚀 Features

- **Coordinator service** (FastAPI)
  - Manages tasks, submissions, and a reputation-based leaderboard
  - Stores state persistently in SQLite (`coordinator.db`)
- **Worker service**
  - Runs local ML inference (DistilBERT sentiment model by default)
  - Fetches tasks, processes them, and submits results
- **Consensus & scoring**
  - Majority voting finalizes task results
  - Workers earn points for matching the final consensus
- **Persistence**
  - All tasks, submissions, and scores survive restarts

---

## ⚙️ Setup

### 1. Clone the repo

```bash
git clone https://github.com/basherxz/ai-market.git
cd ai-market
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

If you’re using VS Code Dev Container, dependencies will install automatically when the container builds.

### 3. Start the coordinator (FastAPI server)

```bash
make dev
```

The coordinator handles:

Task creation

Worker registration

Result verification

Leaderboard scoring

It runs on http://localhost:8000
.

### 4. Start workers (in separate terminals)

Each worker connects to the coordinator and performs inference tasks using Hugging Face Transformers.

```bash
make worker WORKER_ID=alice
make worker WORKER_ID=bob
make worker WORKER_ID=carole
```

### 5. Verify setup

```bash
curl -s http://localhost:8000/health | jq
```

Expected output:

{"ok": true}

### 6. Submit a test task

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"text":"I absolutely love how this works!"}'
```

### 7. View leaderboard

```bash
curl -s http://localhost:8000/leaderboard | jq
```

Expected output:

[
{"worker_id": "alice", "points": 2},
{"worker_id": "bob", "points": 2},
{"worker_id": "carole", "points": 2}
]

## 🧩 Tech Stack

**Python 3.11+ – modern async and typing support**

**FastAPI – lightweight REST framework with automatic OpenAPI docs**

**SQLModel – ORM built on SQLAlchemy and Pydantic**

**SQLite – embedded database for local persistence**

**Hugging Face Transformers – for AI model inference**

**Uvicorn – ASGI web server**

**Makefile + Devcontainer – reproducible development environment**

## 🧠 Next Milestones

### Heartbeat & Reliability

**Let workers send periodic “I’m alive” pings.**

**Reassign stuck tasks automatically if a worker goes offline.**

### Task Categories

**Add a task_type field (sentiment, summarization, translation …)**

**Route each task to a compatible worker model.**

### Redis / PostgreSQL

**Swap the in-memory queue and SQLite for Redis + Postgres to scale horizontally.**

### Authentication

**Simple API-key or token system for registered workers.**

### Web Dashboard

**A small HTML/JS frontend showing live tasks, logs, and leaderboard data.**

### Model Diversity

**Allow workers to specify different HF models and track their accuracy or specialization.**

## 🧪 API Reference

| Method | Endpoint           | Description                                           |
| ------ | ------------------ | ----------------------------------------------------- |
| `GET`  | `/health`          | Returns `{"ok": true}` if the coordinator is running  |
| `POST` | `/tasks`           | Submit a new task payload                             |
| `GET`  | `/tasks`           | List all tasks in the DB                              |
| `GET`  | `/tasks/{task_id}` | Retrieve details and current status                   |
| `POST` | `/tasks/next`      | Worker requests the next unassigned task              |
| `POST` | `/workers/submit`  | Worker submits result for a task                      |
| `GET`  | `/leaderboard`     | Get all worker scores                                 |
| `GET`  | `/db/stats`        | Debug endpoint: number of tasks, submissions, workers |

## 🧱 Directory Overview

```
ai-market/
├── services/
│   ├── coordinator/
│   │   ├── app.py          # FastAPI coordinator API
│   │   ├── db.py           # Database and session helpers
│   │   ├── models.py       # ORM models
│   │   └── __init__.py
│   └── worker/
│       └── worker.py       # ML inference worker
│
├── .devcontainer/          # VS Code Dev Container config
├── Makefile                # Helper commands (make dev, make worker)
├── requirements.txt        # Python dependencies
├── coordinator.db          # SQLite database (auto-generated)
└── README.md
```

## 📈 Example Workflow

### Start the coordinator:

```bash
make dev
```

### Launch one or more workers:

```bash
make worker WORKER_ID=alice
```

### Submit a sample inference task:

```bash
curl -X POST http://localhost:8000/tasks \
     -H "Content-Type: application/json" \
     -d '{"text":"This system works perfectly!"}'
```

### Wait for workers to process it and check:

```bash
curl http://localhost:8000/leaderboard | jq
```

📄 License

MIT License © 2025 [Built by Sint/Basherxz]
Vì một tương lai không phải thiếu nợ.
