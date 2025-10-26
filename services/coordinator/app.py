from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
from collections import defaultdict
import uuid
import time

app = FastAPI(title="AI Market v0")

# --- In-memory stores (v0). We'll swap for Redis/SQLite later. ---
TASKS: Dict[str, Dict] = {}
RESULTS: Dict[str, List[Dict]] = defaultdict(list)
LEADERBOARD: Dict[str, int] = defaultdict(int)
PENDING: List[str] = []                  # FIFO queue of task_ids
ASSIGNMENTS: Dict[str, List[str]] = {}   # task_id -> worker_ids assigned
REQUIRED_SUBMISSIONS = 3                 # how many worker results before verifying

# --- Schemas ---
class CreateTask(BaseModel):
    text: str

class WorkerRegister(BaseModel):
    worker_id: str

class WorkerRequest(BaseModel):
    worker_id: str

class WorkerSubmit(BaseModel):
    worker_id: str
    task_id: str
    label: str          # "positive" or "negative"
    confidence: float   # 0..1


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/tasks")
def create_task(body: CreateTask):
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {
        "id": task_id,
        "text": body.text,
        "status": "queued",
        "created_at": time.time(),
        "final_label": None
    }
    PENDING.append(task_id)
    ASSIGNMENTS[task_id] = []
    return {"task_id": task_id}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {
        **task,
        "submissions": RESULTS.get(task_id, []),
    }


@app.get("/leaderboard")
def leaderboard():
    # return as sorted list
    ranked = sorted(LEADERBOARD.items(), key=lambda x: x[1], reverse=True)
    return [{"worker_id": w, "points": p} for w, p in ranked]


@app.post("/workers/register")
def register_worker(body: WorkerRegister):
    # v0: nothing persistent—just acknowledge
    return {"ok": True, "worker_id": body.worker_id}


@app.post("/tasks/next")
def next_task(body: WorkerRequest):
    """
    Very simple "pull the next task I don't have yet".
    In production you'd use Redis with reservations and a TTL.
    """
    # find first pending task not yet assigned to this worker
    for task_id in list(PENDING):
        if len(ASSIGNMENTS[task_id]) >= REQUIRED_SUBMISSIONS:
            continue
        if body.worker_id not in ASSIGNMENTS[task_id]:
            ASSIGNMENTS[task_id].append(body.worker_id)
            task = TASKS[task_id]
            task["status"] = "assigned"
            return {"task_id": task_id, "text": task["text"]}
    return {"task_id": None, "text": None}  # no work right now


@app.post("/workers/submit")
def submit_result(body: WorkerSubmit):
    task = TASKS.get(body.task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    # store submission (dedupe simple)
    already = [r for r in RESULTS[body.task_id] if r["worker_id"] == body.worker_id]
    if not already:
        RESULTS[body.task_id].append({
            "worker_id": body.worker_id,
            "label": body.label,
            "confidence": body.confidence
        })

    # if we have enough submissions, verify (majority vote)
    if len(RESULTS[body.task_id]) >= REQUIRED_SUBMISSIONS and task["final_label"] is None:
        counts = defaultdict(int)
        for r in RESULTS[body.task_id]:
            counts[r["label"]] += 1
        # majority (break ties by highest average confidence for a label)
        max_votes = max(counts.values())
        majority_labels = [lbl for lbl, c in counts.items() if c == max_votes]
        if len(majority_labels) == 1:
            final_label = majority_labels[0]
        else:
            # tie-breaker: avg confidence per label
            best_label, best_conf = None, -1
            for lbl in majority_labels:
                confs = [r["confidence"] for r in RESULTS[body.task_id] if r["label"] == lbl]
                avg = sum(confs)/len(confs)
                if avg > best_conf:
                    best_label, best_conf = lbl, avg
            final_label = best_label

        task["final_label"] = final_label
        task["status"] = "finalized"

        # award +1 to correct workers
        for r in RESULTS[body.task_id]:
            if r["label"] == final_label:
                LEADERBOARD[r["worker_id"]] += 1

        # remove from queue if still pending
        if body.task_id in PENDING:
            PENDING.remove(body.task_id)

    return {"ok": True, "finalized": task["final_label"] is not None}
