# services/coordinator/app.py
from __future__ import annotations
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import time
from functools import wraps
from sqlmodel import select, delete
from fastapi.responses import HTMLResponse

from .db import init_db, get_session, now_utc
from .models import Task, Submission, WorkerScore, Worker

app = FastAPI(title="AI Market Coordinator")

# ---- Tunables (env-overridable if you like) ----
HEARTBEAT_TTL_SECONDS = 75        # mark worker stale if no heartbeat within this
LEASE_SECONDS = 50                # how long a task lease lasts
REQUEUE_SWEEP_SECONDS = 10        # background sweep interval
MAX_ATTEMPTS_DEFAULT = 5

# ---------- Metrics ----------
REQ_LATENCY = Histogram("api_request_latency_seconds",
                        "Latency of API endpoints", ["route", "method"])
TASK_CREATED = Counter("tasks_created_total", "Tasks created", ["type"])
TASK_CLAIMED = Counter("tasks_claimed_total", "Tasks claimed", ["type"])
TASK_FINALIZED = Counter("tasks_finalized_total",
                         "Tasks finalized", ["type", "final_label"])
TASK_FAILED = Counter("tasks_failed_total", "Tasks failed", ["type"])
WORKER_HEARTBEAT = Counter("worker_heartbeats_total", "Heartbeats received")
QUEUE_DEPTH = Gauge("queue_depth", "Number of tasks by status", [
                    "status"])  # queued/assigned/finalized/failed
WORKERS_GAUGE = Gauge("workers_active", "Number of active workers")


def timed(route_name):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            start = time.time()
            try:
                return fn(*a, **kw)
            finally:
                REQ_LATENCY.labels(route=route_name, method="POST" if route_name.startswith(
                    ("POST", "/")) else "GET").observe(time.time()-start)
        return wrapper
    return deco


# ---- Phase 2 in-memory assignment aid (kept for compatibility) ----
ASSIGNMENTS: Dict[str, List[str]] = {}  # task_id -> [worker_ids]

# ---------- Schemas ----------


class CreateTaskBody(BaseModel):
    text: str
    type: Optional[str] = None  # NEW
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
@timed("POST /workers/heartbeat")
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
    WORKER_HEARTBEAT.inc()
    _update_worker_gauge()
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
@timed("POST /tasks")
def create_task(body: CreateTaskBody):
    from uuid import uuid4
    now = now_utc()
    t = Task(
        id=str(uuid4()),
        text=body.text,
        type=body.type,  # NEW
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
        s.refresh(t)
    TASK_CREATED.labels(t.type or "generic").inc()
    _update_queue_gauges()  # refresh gauges
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
@timed("POST /tasks/next")
def next_task(body: NextTaskBody):
    now = now_utc()
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    worker_caps = None
    with get_session() as s:
        w = s.get(Worker, body.worker_id)
        if w and w.capabilities_json:
            try:
                import json
                worker_caps = set(json.loads(w.capabilities_json) or [])
            except Exception:
                worker_caps = None

        stmt = (
            select(Task)
            .where(Task.status.in_(("queued", "assigned")))
            .order_by(Task.created_at.asc(), Task.id.asc())  # FIFO
        )
        tasks = s.exec(stmt).all()

        for t in tasks:
            if t.status == "finalized" or t.status == "failed":
                continue

            # Capability filter (skip if task type not supported by worker)
            if t.type and worker_caps is not None and t.type not in worker_caps:
                continue

            # If assigned but lease expired -> eligible
            if t.status == "assigned" and t.lease_expires_at and t.lease_expires_at > now:
                # still leased by someone else, skip
                continue

            # Skip only if this worker already submitted for this task (true dedup)
            already_submitted = s.exec(
                select(Submission).where(
                    (Submission.task_id == t.id) & (
                        Submission.worker_id == body.worker_id)
                )
            ).first()
            if already_submitted:
                continue

            # Claim
            t.status = "assigned"
            t.reserved_by = body.worker_id
            t.lease_expires_at = lease_until
            t.attempts = (t.attempts or 0) + 1
            s.add(t)
            s.commit()
            s.refresh(t)

            ASSIGNMENTS.setdefault(t.id, []).append(body.worker_id)
            TASK_CLAIMED.labels(t.type or "generic").inc()
            _update_queue_gauges()
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
            TASK_FINALIZED.labels((t.type or "generic"), best_label).inc()

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
                    TASK_FAILED.labels(t.type or "generic").inc()
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
        # delete children first to satisfy FK constraints
        s.exec(delete(Submission))
        s.exec(delete(Task))
        s.exec(delete(WorkerScore))
        s.exec(delete(Worker))
        s.commit()
    # (optional) refresh metrics after reset
    _update_queue_gauges()
    _update_worker_gauge()
    return {"ok": True, "msg": "All tables cleared."}

# --------- Prometheus Metrics Endpoint ----------


@app.get("/metrics")
def metrics():
    # keep gauges fresh
    _update_queue_gauges()
    _update_worker_gauge()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ---------- Metrics Updaters ----------


def _update_queue_gauges():
    with get_session() as s:
        for st in ("queued", "assigned", "finalized", "failed"):
            cnt = s.exec(select(Task).where(Task.status == st)).all()
            QUEUE_DEPTH.labels(st).set(len(cnt))

# ---------- Worker Gauge Updater ----------


def _update_worker_gauge():
    with get_session() as s:
        workers = s.exec(select(Worker)).all()
        # Active == last_seen within TTL
        cutoff = now_utc() - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
        active = sum(1 for w in workers if w.last_seen and w.last_seen >=
                     cutoff and w.status == "active")
        WORKERS_GAUGE.set(active)

# ---------- Dashboard Endpoints ----------


@app.get("/dashboard/summary")
def dashboard_summary():
    # reuse logic from /db/stats, but add recent activity timestamps if you want
    return db_stats()

# ---------- Recent Tasks / Workers ----------


@app.get("/dashboard/tasks")
def dashboard_tasks():
    # return last N (e.g., 100) tasks sorted by created_at desc
    with get_session() as s:
        rows = s.exec(select(Task).order_by(
            Task.created_at.desc()).limit(100)).all()
        return [{
            "id": r.id, "text": r.text, "type": r.type,
            "status": r.status, "reserved_by": r.reserved_by,
            "lease_expires_at": r.lease_expires_at.isoformat() if r.lease_expires_at else None,
            "attempts": r.attempts, "created_at": r.created_at.isoformat()
        } for r in rows]

# ---------- Recent Workers ----------


@app.get("/dashboard/workers")
def dashboard_workers():
    with get_session() as s:
        rows = s.exec(select(Worker).order_by(Worker.created_at.desc())).all()
        return [{
            "worker_id": w.worker_id, "status": w.status,
            "last_seen": w.last_seen.isoformat() if w.last_seen else None
        } for w in rows]


# ---------- Simple HTML Dashboard ----------
DASHBOARD_HTML = """
<!doctype html><html>
<head>
  <meta charset="utf-8"/><title>Coordinator Dashboard</title>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <style>body{font-family:system-ui;margin:20px} .grid{display:grid;gap:12px;grid-template-columns:repeat(4,1fr)}
  table{border-collapse:collapse;width:100%} th,td{border:1px solid #ddd;padding:6px} th{background:#f7f7f7}</style>
</head>
<body>
  <h1>AI Market — Dashboard</h1>

  <div class="grid" hx-get="/dashboard/summary" hx-trigger="load, every 5s" hx-swap="innerHTML">
    <!-- filled by JSON to HTML via /dashboard/summary below -->
  </div>

  <h2>Workers</h2>
  <div id="workers" hx-get="/dashboard/workers_html" hx-trigger="load, every 5s"></div>

  <h2>Recent Tasks</h2>
  <div id="tasks" hx-get="/dashboard/tasks_html" hx-trigger="load, every 5s"></div>

  <form action="/ops/requeue-stale" method="post"><button>Requeue stale</button></form>
  <form action="/ops/reset" method="post" style="margin-top:8px"><button>Reset (dev)</button></form>
</body></html>
"""
# ---------- Dashboard HTML Endpoints ----------


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    return DASHBOARD_HTML

# ---------- Summary HTML ----------


def _summary_html():
    data = db_stats()
    t = data["tasks_by_status"]
    return f"""
      <div><b>Queued</b><br/>{t.get('queued',0)}</div>
      <div><b>Assigned</b><br/>{t.get('assigned',0)}</div>
      <div><b>Finalized</b><br/>{t.get('finalized',0)}</div>
      <div><b>Failed</b><br/>{t.get('failed',0)}</div>
    """
# ---------- Summary HTML Endpoint ----------


@app.get("/dashboard/summary", response_class=HTMLResponse)
def dashboard_summary_html():
    return _summary_html()

# ---------- Workers HTML Endpoint ----------


@app.get("/dashboard/workers_html", response_class=HTMLResponse)
def workers_html():
    rows = dashboard_workers()
    trs = "".join(
        f"<tr><td>{w['worker_id']}</td><td>{w['status']}</td><td>{w['last_seen'] or '-'}</td></tr>" for w in rows)
    return f"<table><tr><th>Worker</th><th>Status</th><th>Last seen</th></tr>{trs}</table>"

# ---------- Tasks HTML Endpoint ----------


@app.get("/dashboard/tasks_html", response_class=HTMLResponse)
def tasks_html():
    rows = dashboard_tasks()
    trs = "".join(
        f"<tr><td>{r['id']}</td><td>{r.get('type') or '-'}</td><td>{r['status']}</td>"
        f"<td>{r.get('reserved_by') or '-'}</td><td>{r.get('lease_expires_at') or '-'}</td>"
        f"<td>{r['attempts']}</td><td>{r['created_at']}</td></tr>"
        for r in rows)
    return "<table><tr><th>ID</th><th>Type</th><th>Status</th><th>Reserved by</th><th>Lease until</th><th>Attempts</th><th>Created</th></tr>"+trs+"</table>"
