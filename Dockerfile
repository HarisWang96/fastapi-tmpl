# ============================================================
# Generic microservice image
# Build dependencies in the builder stage and copy only the virtual environment
# into the runtime image. uv and its build cache are not shipped to production.
# One Uvicorn process per container; scaling is handled by Kubernetes replicas.
# ============================================================

# Keep the Python image identical in both stages so the virtual environment is portable.
ARG PYTHON_IMAGE=python:3.13-slim

# ---------------- Builder stage ----------------
FROM ${PYTHON_IMAGE} AS builder

WORKDIR /app/api

# Pin uv so dependency installation is reproducible.
RUN pip install --no-cache-dir "uv==0.13.6"

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Install from the lockfile before copying application code to maximize layer caching.
COPY ./pyproject.toml ./uv.lock ./.python-version ./
RUN uv sync --locked --no-dev

# ---------------- Runtime stage ----------------
FROM ${PYTHON_IMAGE}

WORKDIR /app/api

# Reuse the builder virtual environment at the same path and Python version.
COPY --from=builder /app/api/.venv /app/api/.venv

# Copy the application; .dockerignore excludes .venv so this cannot overwrite the environment.
COPY ./ /app/api

# Write logs to stderr for container collection. Loguru file rotation is not safe
# when multiple worker processes write to the same file.
ENV PATH=/app/api/.venv/bin:$PATH \
    PYTHONPATH=/app:/app/api \
    PYTHONUNBUFFERED=1 \
    LOG_TO_FILE=false

# Create a system user with no login shell or home directory.
RUN groupadd --system app \
    && useradd --system --gid app --no-create-home --shell /usr/sbin/nologin app

# Run as a non-root user; application files remain root-owned and read-only to the process.
USER app

# Keep this port aligned with the default CMD and the Kubernetes Service.
EXPOSE 8000

# One process per container: Kubernetes scales with replicas, keeping per-pod
# lifecycle, probes and database pool budgeting predictable. The connection
# ceiling is pool size x databases x replicas.
# Set FORWARDED_ALLOW_IPS to trusted proxy CIDRs when running behind an ingress.
# Keep terminationGracePeriodSeconds at least as long as the graceful shutdown timeout.
# exec replaces the shell so Uvicorn receives SIGTERM as PID 1.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1,::1}\" --timeout-graceful-shutdown 30 --no-access-log"]
