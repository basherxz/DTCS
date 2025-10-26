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
