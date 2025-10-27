# services/coordinator/models.py
from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship, Index


# ---- Phase 2 models (existing) ----
class Task(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID string
    text: str

    # Phase 2
    status: str  # "queued" | "assigned" | "finalized" | (NEW) "failed"
    final_label: Optional[str] = None
    required_submissions: int = 3
    created_at: datetime

    # ---- Phase 3 additions ----
    reserved_by: Optional[str] = Field(default=None, index=True)  # worker_id
    lease_expires_at: Optional[datetime] = Field(default=None, index=True)
    attempts: int = Field(default=0, index=True)
    max_attempts: int = Field(default=5, index=True)
    error_message: Optional[str] = None

    # Helpful indices
    __table_args__ = (
        Index("idx_task_status", "status"),
    )


class Submission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(index=True)
    worker_id: str = Field(index=True)
    label: str
    confidence: float
    created_at: datetime


class WorkerScore(SQLModel, table=True):
    worker_id: str = Field(primary_key=True)
    points: int


# ---- Phase 3: Workers table for heartbeats/status ----
class Worker(SQLModel, table=True):
    worker_id: str = Field(primary_key=True)
    status: str = Field(default="active")  # "active" | "stale" | "offline"
    last_seen: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    capabilities_json: Optional[str] = None
