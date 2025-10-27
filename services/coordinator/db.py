# services/coordinator/db.py
from __future__ import annotations
from sqlmodel import SQLModel, Session, create_engine
from contextlib import contextmanager
from typing import Iterator
from datetime import datetime
import sqlite3
import os

from .models import Task, Submission, WorkerScore, Worker

DB_PATH = os.environ.get("DB_PATH", "coordinator.db")
engine = create_engine(
    f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    # Create tables if they don't exist
    SQLModel.metadata.create_all(engine)
    # Minimal migrations for Phase 3 fields on Task (idempotent)
    _apply_sqlite_safe_migrations()


def _apply_sqlite_safe_migrations() -> None:
    # Add columns if missing (SQLite-friendly, harmless if already exist)
    with engine.begin() as conn:
        # Introspect existing columns
        cols = {row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info('task')")}
        # task => reserved_by, lease_expires_at, attempts, max_attempts, error_message
        if "reserved_by" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE task ADD COLUMN reserved_by TEXT")
        if "lease_expires_at" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE task ADD COLUMN lease_expires_at DATETIME")
        if "attempts" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE task ADD COLUMN attempts INTEGER DEFAULT 0")
        if "max_attempts" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE task ADD COLUMN max_attempts INTEGER DEFAULT 5")
        if "error_message" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE task ADD COLUMN error_message TEXT")

        # tasks.status may need to support "failed"; nothing to migrate structurally.

        # Workers table created by metadata.create_all


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def now_utc() -> datetime:
    return datetime.utcnow()
