import sqlite3
conn = sqlite3.connect("coordinator.db")
for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table';"):
    print("\n===", row[0], "===\n", row[1])
conn.close()
