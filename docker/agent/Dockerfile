# Agent Hub — Agent Runtime Container
#
# Provides Claude Code agents running in tmux sessions,
# connected to the daemon container via MCP proxy.
#
# Usage: docker compose --profile agents up --build
#
# Authentication (set one of these):
#   CLAUDE_CODE_OAUTH_TOKEN  — from `claude setup-token` (requires Pro/Max)
#   ANTHROPIC_API_KEY        — API key from console.anthropic.com

FROM ubuntu:24.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# ---------- System packages ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux \
    git \
    curl \
    jq \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ---------- Node.js 20 ----------
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# ---------- uv (Python package manager) ----------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ---------- PyYAML (for config scripts) ----------
RUN pip3 install --break-system-packages pyyaml

# ---------- Claude Code CLI ----------
# Installed at build time for faster container startup.
# Updates can be applied by rebuilding the image.
RUN npm install -g @anthropic-ai/claude-code

# ---------- Workspace ----------
WORKDIR /app

# ---------- Entrypoint ----------
COPY docker/agent/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
