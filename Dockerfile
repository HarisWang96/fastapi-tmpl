# Build stage
FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Production stage
FROM python:3.13-slim

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV LOG_TO_FILE=false

# Copy application code
COPY . .

# The service only needs read access to its code and writes logs to stderr.
RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /opt/prod-sim \
    && chown -R app:app /app
USER app

# Expose port
EXPOSE 8000

# Default command (can be overridden)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
