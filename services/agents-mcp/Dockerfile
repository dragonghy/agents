# Multi-stage Dockerfile for agents-mcp daemon + Web UI
# Usage: docker compose up (from repo root)

# ---------- Stage 1: Build Web UI ----------
FROM node:20-alpine AS web-builder

WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts

COPY web/ ./
# Build outputs to ../src/agents_mcp/web/static/ relative to web dir,
# but in Docker we redirect to a clean output path.
RUN mkdir -p /out/static && \
    npx tsc -b && \
    npx vite build --outDir /out/static --emptyOutDir

# ---------- Stage 2: Python runtime ----------
FROM python:3.12-slim AS runtime

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src/ ./src/

# Copy built web static files into the expected location
COPY --from=web-builder /out/static/ ./src/agents_mcp/web/static/

# Install the project itself
RUN uv sync --frozen --no-dev

# Config is bind-mounted at runtime
ENV AGENTS_CONFIG_PATH=/config/agents.yaml

EXPOSE 8765

# Run as daemon, bind to all interfaces (required for Docker networking)
CMD ["uv", "run", "agents-mcp", "--daemon", "--host", "0.0.0.0", "--port", "8765"]
