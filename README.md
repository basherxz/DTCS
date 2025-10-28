# Distributed Task Coordination System

A lightweight, reliable framework for orchestrating distributed work across multiple workers.

# About This Project

What started as a small experiment in queue management quietly evolved into something bigger — **an attempt to teach code how to organize itself**.

This system isn’t just a task runner; it’s a sandbox for exploring reliability, autonomy, and scale.
The kind of thing that, in another life, might grow into a research framework, a distributed compute layer, or even the nervous system of a larger platform.

It was built out of equal parts curiosity and stubbornness — a personal challenge to design something that keeps going, even when parts of it fail.

# Key Features

- **Distributed orchestration:** assign and coordinate tasks across multiple workers.

- **Lease-based reliability:** each worker “rents” a task, ensuring progress even if one disappears.

- **Automatic recovery:** expired leases and failed tasks are automatically re-queued.

- **Extensible design:** plug in new task types or integrate with existing systems.

- **Stateless workers:** scale up or down seamlessly — no manual management required.

# Architecture Overview

```
flowchart LR
  subgraph Coordinator
    API[API Server] --> DB[(Task Database)]
  end
  subgraph Workers
    W1[Worker 1]
    W2[Worker 2]
    W3[Worker 3]
  end
  Client -->|Submit Task| API
  API -->|Assign Task| W1 & W2 & W3
  W1 & W2 & W3 -->|Report Status / Renew Lease| API
  API -->|Persist State| DB
```

Each worker communicates with the coordinator through a clean REST API — claiming, renewing, or completing tasks.
If a worker vanishes, the coordinator notices and reassigns the task, ensuring that no work is ever lost.

# Design Philosophy

This project follows a few core ideas that guide every decision:

- **Reliability Through Simplicity**

  - Complexity hides failure. By keeping logic explicit and state visible, reliability becomes inspectable and testable.

- **Assume Failure, Design for Recovery**

  - Every part of the system — worker, lease, or task — is treated as unreliable.
  - The system’s job is not to prevent failure, but to recover gracefully from it.

- **State Is Truth**

  - The database is the brain. Everything else — workers, API servers — can crash, restart, or vanish.
  - As long as state persists, the system can rebuild itself.

- **Clarity Over Cleverness**

  - Code should explain itself. If you need a diagram to understand the flow, the code has failed in its duty.

- **Progress Over Perfection**
  - A system that moves — even imperfectly — is better than one that waits for ideal design.
  - Movement generates learning; learning generates resilience.

These principles serve as both engineering rules and personal reminders — the system grows sturdier the same way its creator does: one iteration at a time.

# Roadmap

- [x] Core leasing and task assignment logic

- [x] Heartbeats and reliability layer (auto-lease renewal)

- [x] Metrics and dashboard for visibility

- [ ] Next: Plugin task runners (custom task logic)

- [ ] Coordinator clustering for horizontal scaling

# Project Goal

> “To create a self-coordinating distributed task system that embodies reliability, autonomy, and scale —
> and to prove, through its existence, that complex systems can be built from first principles.”

This project is both a technical and philosophical exploration:
Can a simple, human-written program behave like a self-managing organism?
Can reliability emerge from simplicity?

That’s what’s waiting at the end of this road.

# Tech Stack

- Python 3.11+

- FastAPI for coordination

- SQLite / PostgreSQL for state

- HTTPX for worker communication

- Docker (optional) for deployment

# Getting Started

```bash
# Start the coordinator
uvicorn coordinator:app --reload

# Run a worker
python worker.py --worker-id w1

# Submit a task
curl -X POST localhost:8000/tasks -H "Content-Type: application/json" -d '{"data":"example"}'
```

# License

MIT — free to use, modify, and extend. Contributions welcome. Created by **Si Nguyen** (_Sint/Basherxz_), 2025.

> Vì một tương lai không phải trả nợ
