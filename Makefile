# Makefile at repo root
PYTHON=python
COORD_HOST=0.0.0.0
COORD_PORT=8000

# set a default HF cache (matches your devcontainer remoteEnv)
export HF_HOME ?= /workspaces/repo/.hf-cache

dev:
	$(PYTHON) -m uvicorn services.coordinator.app:app --host $(COORD_HOST) --port $(COORD_PORT) --reload

worker:
	@if [ -z "$$WORKER_ID" ]; then echo "Usage: make worker WORKER_ID=alice"; exit 1; fi
	$(PYTHON) services/worker/worker.py
