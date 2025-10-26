from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, Column, String, Integer, Float, DateTime


class Task(SQLModel, table=True):
    id: str = Field(primary_key=True, index=True)
    text: str
    # queued|assigned|finalized
    status: str = Field(default="queued", index=True)
    final_label: Optional[str] = None
    required_submissions: int = Field(default=3)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Submission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, foreign_key="task.id")
    worker_id: str = Field(index=True)
    label: str
    confidence: float
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkerScore(SQLModel, table=True):
    worker_id: str = Field(primary_key=True)
    points: int = Field(default=0)
