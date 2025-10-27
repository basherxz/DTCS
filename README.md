# 🧠 Distributed Task Coordination System

- Không hi vọng nhiều nhưng cũng phải cố gắng hết mình trước đã

A lightweight experimental framework for coordinating and verifying distributed AI inference jobs across multiple worker nodes.  
Built with **FastAPI**, **SQLModel**, and **Hugging Face Transformers** — inspired by decentralized AI compute networks like Bittensor.

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

## 🧱 Directory Overview

```
.devcontainer/
  ├─ Dockerfile
  ├─ devcontainer.json
  └─ requirements.txt
services/
  ├─ coordinator/
  │  ├─ __init__.py
  │  ├─ app.py          # FastAPI app + endpoints
  │  ├─ db.py           # SQLModel engine + session + init
  │  └─ models.py       # Task, Submission, WorkerScore
  └─ worker/
     └─ worker.py       # (stateless loop; not shown here)
.gitignore
Makefile
README.md
coordinator.db
db_check.py
docker-compose.dev.yml
```

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

---

## 🧩 Tech Stack

**Python 3.11+ – modern async and typing support**

**FastAPI – lightweight REST framework with automatic OpenAPI docs**

**SQLModel – ORM built on SQLAlchemy and Pydantic**

**SQLite – embedded database for local persistence**

**Hugging Face Transformers – for AI model inference**

**Uvicorn – ASGI web server**

**Makefile + Devcontainer – reproducible development environment**

---

## Heartbeats & Reliability

This release introduces a real lease system, worker heartbeats, and automatic task recovery.
It’s still fully backward-compatible with previous phases.

### New concepts

| Feature             | Purpose                                                                                    | Key fields / endpoints                                                            |
| ------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| **Leases**          | Prevent two workers from claiming the same task simultaneously.                            | `Task.lease_expires_at`, `Task.reserved_by`, `Task.attempts`, `Task.max_attempts` |
| **Heartbeats**      | Let the coordinator know a worker is alive and optionally renew leases for tasks it holds. | `POST /workers/heartbeat`                                                         |
| **Auto-requeue**    | Reclaim tasks whose lease expired or whose worker went stale.                              | background sweeper + `POST /ops/requeue-stale`                                    |
| **Worker registry** | Track status (`active / stale / offline`) and capabilities.                                | `Worker` table, `POST /workers/register`                                          |

### Quick start

- Start coordinator

```bash
uvicorn services.coordinator.app:app --reload --port 8000
```

- Register workers

```bash
curl -sX POST localhost:8000/workers/register  -H 'Content-Type: application/json' -d '{"worker_id":"w1"}'
curl -sX POST localhost:8000/workers/heartbeat -H 'Content-Type: application/json' -d '{"worker_id":"w1"}'
```

- Enqueue a task

```bash
curl -sX POST localhost:8000/tasks -H 'Content-Type: application/json' -d '{"text":"Reliability test headline"}'
```

- Claim & inspect

```bash
curl -sX POST localhost:8000/tasks/next -H 'Content-Type: application/json' -d '{"worker_id":"w1"}'
curl -s localhost:8000/tasks | jq 'map({id,status,reserved_by,lease_expires_at,attempts})'
```

- Submit a result

```bash
curl -sX POST localhost:8000/workers/submit -H 'Content-Type: application/json' \
     -d '{"worker_id":"w1","task_id":"<uuid>","label":"positive","confidence":0.9}'
```

### Configurable tunables

| Variable                | Default | Description                                                              |
| ----------------------- | ------- | ------------------------------------------------------------------------ |
| `HEARTBEAT_TTL_SECONDS` | 45      | Worker marked stale if no heartbeat within this window.                  |
| `LEASE_SECONDS`         | 75      | How long a claimed task stays reserved before it’s eligible for requeue. |
| `REQUEUE_SWEEP_SECONDS` | 15      | How often the background thread checks for expired leases.               |
| `MAX_ATTEMPTS_DEFAULT`  | 5       | Maximum claim attempts before a task becomes `failed`.                   |

Override by editing services/coordinator/app.py or exporting environment variables before launch.

### Maintenance & testing endpoints

| Endpoint                  | Purpose                                                                        |
| ------------------------- | ------------------------------------------------------------------------------ |
| `POST /ops/requeue-stale` | Manually force a requeue sweep.                                                |
| `POST /ops/reset`         | _(dev only)_ Clear all tables (`task`, `submission`, `worker`, `workerscore`). |
| `GET /db/stats`           | Summary counts for tasks, submissions, and workers.                            |
| `GET /leaderboard`        | Worker scores and ranking.                                                     |

### Typical lifecycle

Worker registers + heartbeats
→ appears in /db/stats and remains active.

Worker claims a task via '/tasks/next'.
→ coordinator marks task assigned and sets lease_expires_at.

Worker sends heartbeats while working.
→ each heartbeat renews the lease.

Worker submits results.
→ task finalizes after reaching required_submissions.

If the worker crashes or stops heartbeating,
→ the sweeper requeues the task when the lease expires.

### Development helpers

| Command                                  | Description                          |
| ---------------------------------------- | ------------------------------------ |
| `curl -s localhost:8000/health`          | simple health check                  |
| `curl -s localhost:8000/tasks`           | list all tasks                       |
| `curl -s localhost:8000/tasks/<id>`      | inspect a specific task              |
| `curl -sX POST localhost:8000/ops/reset` | wipe everything                      |
| `sqlite3 coordinator.db '.tables'`       | inspect DB (if SQLite CLI installed) |

---

## 🧠 Next Milestones

**Heartbeat & Reliability** (Done)

- Let workers send periodic “I’m alive” pings.

- Reassign stuck tasks automatically if a worker goes offline.

**Task Categories**

- Add a task_type field (sentiment, summarization, translation …)\*\*

- Route each task to a compatible worker model.\*\*

**Redis / PostgreSQL**

- Swap the in-memory queue and SQLite for Redis + Postgres to scale horizontally.\*\*

**Authentication**

- Simple API-key or token system for registered workers.\*\*

**Web Dashboard**

- A small HTML/JS frontend showing live tasks, logs, and leaderboard data.\*\*

**Model Diversity**

- Allow workers to specify different HF models and track their accuracy or specialization.\*\*

---

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

---

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

---

## 📄 License

**MIT License © 2025 [Built by Sint/Basherxz]**

- Vì một tương lai không phải thiếu nợ.
