FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source code and pre-built frontend
COPY src/ src/
COPY web/dist/ web/dist/

EXPOSE 3000

CMD ["uv", "run", "python", "-m", "management.app"]
