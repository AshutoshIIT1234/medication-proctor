# ── Stage 1: build ─────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first (better layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies into /app/.venv (no-install-project = skip dev extras)
RUN uv sync --frozen --no-install-project --no-dev

# ── Stage 2: runtime ────────────────────────────────────────────────────────────
FROM python:3.13-slim

# System dependency for OpenCV / image libs used by ultralytics/roboflow
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY . .

# Make uv-installed binaries available on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Expose the HTTP server port
EXPOSE 8080

# Health check (Vision Agents exposes /health)
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Run in server mode so the container can handle multiple concurrent sessions
CMD ["python", "main.py", "serve", "--host", "0.0.0.0", "--port", "8080"]
