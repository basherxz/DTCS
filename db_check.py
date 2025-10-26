import sqlite3
import json
con = sqlite3.connect("coordinator.db")
cur = con.cursor()
print("Tables:", cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall())
print("WorkerScore:", cur.execute(
    "SELECT worker_id, points FROM workerscore ORDER BY points DESC").fetchall())
print("Tasks (last 5):", cur.execute(
    "SELECT id, status, final_label FROM task ORDER BY created_at DESC LIMIT 5").fetchall())
print("Submissions (count):", cur.execute(
    "SELECT COUNT(*) FROM submission").fetchone())
con.close()
