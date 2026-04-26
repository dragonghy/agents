.PHONY: install dev build run test clean

# Repo root (parent dir three levels up from this Makefile)
REPO_ROOT := $(shell cd ../.. && pwd)

install:
	cd backend && uv sync
	cd frontend && npm install

dev:
	@echo "Starting backend on :3000 and frontend dev on :3001"
	@echo "Open http://localhost:3001 (Vite proxies /api -> :3000)"
	@( cd backend && AGENTS_REPO_ROOT=$(REPO_ROOT) uv run uvicorn app.main:app --host 127.0.0.1 --port 3000 --reload ) & \
	( cd frontend && npm run dev ) ; \
	wait

build:
	cd frontend && npm run build
	@echo "Built frontend into backend/app/static/"

run:
	cd backend && AGENTS_REPO_ROOT=$(REPO_ROOT) uv run uvicorn app.main:app --host 127.0.0.1 --port 3000

test:
	cd backend && AGENTS_REPO_ROOT=$(REPO_ROOT) uv run pytest -v

clean:
	rm -rf backend/app/static/* frontend/dist
	rm -rf frontend/node_modules backend/.venv
