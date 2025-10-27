# services/coordinator/app.py
from __future__ import annotations
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta

from sqlmodel import select

from .db import init_db, get_session, now_utc
from .models import Task, Submission, WorkerScore, Worker

app = FastAPI(title="AI Market Coordinator")

# ---- Tunables (env-overridable if you like) ----
HEARTBEAT_TTL_SECONDS = 75        # mark worker stale if no heartbeat within this
LEASE_SECONDS = 50                # how long a task lease lasts
REQUEUE_SWEEP_SECONDS = 10        # background sweep interval
MAX_ATTEMPTS_DEFAULT = 5

# ---- Phase 2 in-memory assignment aid (kept for compatibility) ----
ASSIGNMENTS: Dict[str, List[str]] = {}  # task_id -> [worker_ids]

# ---------- Schemas ----------


class CreateTaskBody(BaseModel):
    text: str
    required_submissions: Optional[int] = 3
    max_attempts: Optional[int] = MAX_ATTEMPTS_DEFAULT


class NextTaskBody(BaseModel):
    worker_id: str


class SubmitBody(BaseModel):
    worker_id: str
    task_id: str
    label: str
    confidence: float


class RegisterBody(BaseModel):
    worker_id: str
    capabilities_json: Optional[str] = None


class HeartbeatBody(BaseModel):
    worker_id: str


# ---------- Lifecycle ----------
@app.on_event("startup")
def _startup() -> None:
    init_db()
    # Start a lightweight sweep to mark stale workers and requeue expired leases
    import threading
    import time

    def sweeper():
        while True:
            try:
                _mark_stale_workers()
                _requeue_expired()
            except Exception:
                # Keep daemon alive no matter what
                pass
            time.sleep(REQUEUE_SWEEP_SECONDS)
    t = threading.Thread(target=sweeper, daemon=True)
    t.start()


@app.get("/health")
def health():
    return {"ok": True}


# ---------- Workers ----------
@app.post("/workers/register")
def register_worker(body: RegisterBody):
    now = now_utc()
    with get_session() as s:
        w = s.get(Worker, body.worker_id)
        if not w:
            w = Worker(worker_id=body.worker_id, status="active",
                       last_seen=now, capabilities_json=body.capabilities_json)
            s.add(w)
        else:
            w.status = "active"
            w.last_seen = now
            if body.capabilities_json:
                w.capabilities_json = body.capabilities_json
        s.commit()
    return {"ok": True}


@app.post("/workers/heartbeat")
def heartbeat(body: HeartbeatBody):
    now = now_utc()
    with get_session() as s:
        w = s.get(Worker, body.worker_id)
        if not w:
            # auto-register on first heartbeat
            w = Worker(worker_id=body.worker_id,
                       status="active", last_seen=now)
            s.add(w)
        else:
            w.status = "active"
            w.last_seen = now
            # ⬇️ NEW: extend leases for any tasks reserved by this worker
        lease_until = now + timedelta(seconds=LEASE_SECONDS)
        from sqlmodel import select
        held = s.exec(
            select(Task).where((Task.status == "assigned")
                               & (Task.reserved_by == body.worker_id))
        ).all()
        for t in held:
            t.lease_expires_at = lease_until
        s.commit()
    return {"ok": True, "ts": now.isoformat()}


def _mark_stale_workers():
    cutoff = now_utc() - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
    with get_session() as s:
        stmt = select(Worker).where((Worker.last_seen.is_not(None)) & (
            Worker.last_seen < cutoff) & (Worker.status != "stale"))
        for w in s.exec(stmt).all():
            w.status = "stale"
        s.commit()


# ---------- Tasks ----------
@app.post("/tasks")
def create_task(body: CreateTaskBody):
    from uuid import uuid4
    now = now_utc()
    t = Task(
        id=str(uuid4()),
        text=body.text,
        status="queued",
        final_label=None,
        required_submissions=body.required_submissions or 3,
        created_at=now,
        reserved_by=None,
        lease_expires_at=None,
        attempts=0,
        max_attempts=body.max_attempts or MAX_ATTEMPTS_DEFAULT,
        error_message=None,
    )
    with get_session() as s:
        s.add(t)
        s.commit()
        s.refresh(t)  # ensures attributes are loaded and not expired
    return {"task_id": t.id}


@app.get("/tasks")
def list_tasks(status: Optional[str] = None):
    with get_session() as s:
        if status:
            stmt = select(Task).where(Task.status == status)
        else:
            stmt = select(Task)
        rows = s.exec(stmt).all()
        return [
            {
                "id": r.id,
                "text": r.text,
                "status": r.status,
                "final_label": r.final_label,
                "required_submissions": r.required_submissions,
                "attempts": r.attempts,
                "max_attempts": r.max_attempts,
                "reserved_by": r.reserved_by,
                "lease_expires_at": r.lease_expires_at.isoformat() if r.lease_expires_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    with get_session() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(404, "Task not found")
        subs = s.exec(select(Submission).where(Submission.task_id ==
                      task_id).order_by(Submission.created_at)).all()
        return {
            "task": {
                "id": t.id,
                "text": t.text,
                "status": t.status,
                "final_label": t.final_label,
                "required_submissions": t.required_submissions,
                "attempts": t.attempts,
                "max_attempts": t.max_attempts,
                "reserved_by": t.reserved_by,
                "lease_expires_at": t.lease_expires_at.isoformat() if t.lease_expires_at else None,
                "created_at": t.created_at.isoformat(),
            },
            "submissions": [
                {
                    "worker_id": s_.worker_id,
                    "label": s_.label,
                    "confidence": s_.confidence,
                    "created_at": s_.created_at.isoformat(),
                }
                for s_ in subs
            ],
        }


@app.post("/tasks/next")
def next_task(body: NextTaskBody):
    now = now_utc()
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    with get_session() as s:
        # Prefer queued tasks; ignore finalized/failed
        stmt = select(Task).where(Task.status.in_(("queued", "assigned"))).order_by(
            Task.created_at.asc(), Task.id.asc())
        tasks = s.exec(stmt).all()

        # Filter out finalized and failed, and those that already met required_submissions
        eligible: List[Task] = []
        for t in tasks:
            if t.status == "finalized" or t.status == "failed":
                continue
            # Keep if queued, or assigned but lease expired
            if t.status == "queued":
                eligible.append(t)
            elif t.status == "assigned" and (t.lease_expires_at is None or t.lease_expires_at <= now):
                eligible.append(t)

        # Skip ones this worker already handled in this process memory
        for t in eligible:
            if ASSIGNMENTS.get(t.id) and body.worker_id in ASSIGNMENTS[t.id]:
                continue

            # Claim this one atomically
            t.status = "assigned"
            t.reserved_by = body.worker_id
            t.lease_expires_at = lease_until
            t.attempts = (t.attempts or 0) + 1
            s.add(t)
            # update memory helper
            ASSIGNMENTS.setdefault(t.id, []).append(body.worker_id)
            s.commit()
            return {"task_id": t.id, "text": t.text}

    return {"task_id": None, "text": None}


@app.post("/workers/submit")
def submit_result(body: SubmitBody):
    now = now_utc()
    with get_session() as s:
        t = s.get(Task, body.task_id)
        if not t:
            raise HTTPException(404, "Task not found")

        # Dedup submission (one per worker per task)
        existing = s.exec(
            select(Submission).where(
                (Submission.task_id == body.task_id) & (
                    Submission.worker_id == body.worker_id)
            )
        ).first()
        if existing:
            return {"ok": True, "duplicate": True}

        s.add(Submission(
            task_id=body.task_id,
            worker_id=body.worker_id,
            label=body.label,
            confidence=body.confidence,
            created_at=now,
        ))

        # Evaluate for finalization
        subs = s.exec(select(Submission).where(
            Submission.task_id == body.task_id)).all()
        if len(subs) >= (t.required_submissions or 3) and not t.final_label:
            # Majority vote with confidence tiebreak
            by_label: Dict[str, List[Submission]] = {}
            for sub in subs:
                by_label.setdefault(sub.label, []).append(sub)
            # majority
            best_label = None
            best_count = -1
            for label, arr in by_label.items():
                if len(arr) > best_count:
                    best_count = len(arr)
                    best_label = label
                elif len(arr) == best_count:
                    # tie -> avg confidence
                    def avg(l): return sum(x.confidence for x in l) / len(l)
                    if avg(arr) > avg(by_label[best_label]):
                        best_label = label

            t.final_label = best_label
            t.status = "finalized"
            t.reserved_by = None
            t.lease_expires_at = None

            # Award points
            winners = [sub.worker_id for sub in subs if sub.label == best_label]
            for wid in set(winners):
                ws = s.get(WorkerScore, wid)
                if not ws:
                    ws = WorkerScore(worker_id=wid, points=1)
                    s.add(ws)
                else:
                    ws.points += 1

        s.commit()
    return {"ok": True}


# ---------- Requeue / Maintenance ----------
@app.post("/ops/requeue-stale")
def manual_requeue():
    count = _requeue_expired()
    return {"requeued": count}


def _requeue_expired() -> int:
    now = now_utc()
    cutoff_worker = now - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
    count = 0
    with get_session() as s:
        stmt = select(Task).where(Task.status == "assigned")
        for t in s.exec(stmt).all():
            lease_expired = (t.lease_expires_at and t.lease_expires_at <= now)
            worker_stale = False
            if t.reserved_by:
                w = s.get(Worker, t.reserved_by)
                # Only treat as stale if the worker EXISTS and is past cutoff or marked stale.
                if w and ((not w.last_seen) or (w.last_seen < cutoff_worker) or (w.status == "stale")):
                    worker_stale = True

            if lease_expired or worker_stale:
                if (t.attempts or 0) >= (t.max_attempts or MAX_ATTEMPTS_DEFAULT):
                    t.status = "failed"
                    t.error_message = (
                        t.error_message or "max attempts reached")
                    t.reserved_by = None
                    t.lease_expires_at = None
                else:
                    t.status = "queued"
                    t.reserved_by = None
                    t.lease_expires_at = None
                s.add(t)
                count += 1
        s.commit()
    return count


# ---------- Stats / Leaderboard ----------
@app.get("/leaderboard")
def leaderboard():
    with get_session() as s:
        rows = s.exec(select(WorkerScore).order_by(
            WorkerScore.points.desc())).all()
        return [{"worker_id": r.worker_id, "points": r.points} for r in rows]


@app.get("/db/stats")
def db_stats():
    with get_session() as s:
        total_tasks = s.exec(select(Task)).all()
        submissions = s.exec(select(Submission)).all()
        workers = s.exec(select(Worker)).all()
        by_status = {"queued": 0, "assigned": 0, "finalized": 0, "failed": 0}
        for t in total_tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
        # stale workers
        cutoff = now_utc() - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
        stale = [w for w in workers if (w.last_seen and w.last_seen < cutoff)]
        return {
            "tasks_total": len(total_tasks),
            "tasks_by_status": by_status,
            "submissions": len(submissions),
            "workers": len(workers),
            "workers_stale": len(stale),
        }

# ---------- Reset endpoint (clear tables) ----------


@app.post("/ops/reset")
def reset_db():
    with get_session() as s:
        s.exec("DELETE FROM submission")
        s.exec("DELETE FROM task")
        s.exec("DELETE FROM workerscore")
        s.exec("DELETE FROM worker")
        s.commit()
    return {"ok": True, "msg": "All tables cleared."}
