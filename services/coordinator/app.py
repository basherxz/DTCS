# services/coordinator/app.py
from collections import defaultdict
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select, func

from .db import init_db, get_session
from .models import Task, Submission, WorkerScore

# -----------------------
# FastAPI app setup
# -----------------------
app = FastAPI(title="AI Market v1 (SQLite)")

# Initialize DB on startup


@app.on_event("startup")
def on_startup():
    init_db()


# -----------------------
# In-memory helpers
# -----------------------
# Tracks which workers have been assigned to a task (lightweight helper; source of truth is DB)
ASSIGNMENTS: Dict[str, List[str]] = {}  # task_id -> [worker_ids]
REQUIRED_SUBMISSIONS = 3                # quorum for finalization

# -----------------------
# Request Schemas
# -----------------------


class CreateTask(BaseModel):
    text: str


class WorkerRegister(BaseModel):
    worker_id: str


class WorkerRequest(BaseModel):
    worker_id: str


class WorkerSubmit(BaseModel):
    worker_id: str
    task_id: str
    label: str            # "positive" | "negative"
    confidence: float     # 0..1

# -----------------------
# Health
# -----------------------


@app.get("/health")
def health():
    return {"ok": True}

# -----------------------
# Tasks
# -----------------------


@app.post("/tasks")
def create_task(body: CreateTask, session: Session = Depends(get_session)):
    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        text=body.text,
        status="queued",
        required_submissions=REQUIRED_SUBMISSIONS,
    )
    session.add(task)
    session.commit()
    ASSIGNMENTS[task_id] = []
    return {"task_id": task_id}


@app.get("/tasks")
def list_tasks(
    status: Optional[str] = Query(
        default=None, description="Filter by status: queued|assigned|finalized"),
    session: Session = Depends(get_session),
):
    stmt = select(Task)
    if status:
        stmt = stmt.where(Task.status == status)
    tasks = session.exec(stmt).all()
    return [
        {
            "id": t.id,
            "text": t.text,
            "status": t.status,
            "final_label": t.final_label,
            "required_submissions": t.required_submissions,
        }
        for t in tasks
    ]


@app.get("/tasks/{task_id}")
def get_task(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    subs = session.exec(select(Submission).where(
        Submission.task_id == task_id)).all()
    return {
        "id": task.id,
        "text": task.text,
        "status": task.status,
        "final_label": task.final_label,
        "required_submissions": task.required_submissions,
        "submissions": [
            {"worker_id": s.worker_id, "label": s.label, "confidence": s.confidence}
            for s in subs
        ],
    }

# -----------------------
# Workers
# -----------------------


@app.post("/workers/register")
def register_worker(_: WorkerRegister):
    # Placeholder for future identity/auth; returns OK so workers can proceed
    return {"ok": True}


@app.post("/tasks/next")
def next_task(body: WorkerRequest, session: Session = Depends(get_session)):
    """
    Returns the next available task that:
      - is not finalized
      - still needs submissions (< required_submissions)
      - hasn't already been assigned to this worker (per ASSIGNMENTS helper)
    """
    tasks = session.exec(select(Task).where(Task.status != "finalized")).all()
    for t in tasks:
        assigned = ASSIGNMENTS.setdefault(t.id, [])
        # how many submissions already exist for this task?
        subs_count = len(session.exec(
            select(Submission).where(Submission.task_id == t.id)).all())
        if subs_count >= t.required_submissions:
            continue
        if body.worker_id in assigned:
            continue

        # assign to this worker
        assigned.append(body.worker_id)

        if t.status == "queued":
            t.status = "assigned"
            session.add(t)
            session.commit()

        return {"task_id": t.id, "text": t.text}

    return {"task_id": None, "text": None}  # no work right now


@app.post("/workers/submit")
def submit_result(body: WorkerSubmit, session: Session = Depends(get_session)):
    task = session.get(Task, body.task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    # Deduplicate: only one submission per (worker, task)
    existing = session.exec(
        select(Submission).where(
            (Submission.task_id == body.task_id) & (
                Submission.worker_id == body.worker_id)
        )
    ).first()
    if not existing:
        session.add(
            Submission(
                task_id=body.task_id,
                worker_id=body.worker_id,
                label=body.label,
                confidence=body.confidence,
            )
        )
        session.commit()

    # Check if we can finalize
    subs = session.exec(select(Submission).where(
        Submission.task_id == body.task_id)).all()
    if task.final_label is None and len(subs) >= task.required_submissions:
        # Majority vote
        counts: Dict[str, int] = defaultdict(int)
        for s in subs:
            counts[s.label] += 1

        max_votes = max(counts.values())
        majority_labels = [lbl for lbl, c in counts.items() if c == max_votes]

        if len(majority_labels) == 1:
            final = majority_labels[0]
        else:
            # tie-break: highest average confidence
            best_lbl, best_conf = None, -1.0
            for lbl in majority_labels:
                confs = [s.confidence for s in subs if s.label == lbl]
                avg = sum(confs) / len(confs)
                if avg > best_conf:
                    best_lbl, best_conf = lbl, avg
            final = best_lbl

        # Persist finalization
        task.final_label = final
        task.status = "finalized"
        session.add(task)

        # Award points to matching workers
        winners = {s.worker_id for s in subs if s.label == final}
        for wid in winners:
            row = session.get(WorkerScore, wid)
            if not row:
                row = WorkerScore(worker_id=wid, points=0)
            row.points += 1
            session.add(row)

        session.commit()

    return {"ok": True, "finalized": task.final_label is not None}

# -----------------------
# Leaderboard
# -----------------------


@app.get("/leaderboard")
def leaderboard(session: Session = Depends(get_session)):
    rows = session.exec(select(WorkerScore)).all()
    rows.sort(key=lambda r: r.points, reverse=True)
    return [{"worker_id": r.worker_id, "points": r.points} for r in rows]


@app.get("/db/stats")
def db_stats(session: Session = Depends(get_session)):
    tasks = session.exec(select(func.count(Task.id))).one()
    subs = session.exec(select(func.count(Submission.id))).one()
    wrks = session.exec(select(func.count(WorkerScore.worker_id))).one()
    return {"tasks": tasks, "submissions": subs, "workers": wrks}
