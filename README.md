# FastAPI PostgreSQL + Redis Service Template

Minimal production-oriented FastAPI service template. It includes:

- FastAPI with async SQLAlchemy and PostgreSQL
- Async Redis client with connection pooling and timeouts
- Alembic migrations
- Liveness, readiness and dependency health checks
- A validated demo route
- Docker Compose for API, PostgreSQL and Redis

## Run locally

```bash
uv sync
cp .env.example .env
uv run alembic upgrade head
./scripts/start.sh
```

Development reload:

```bash
RELOAD=true ./scripts/start.sh
```

## Run with Docker Compose

```bash
docker compose up --build
```

Run migrations as a separate release step:

```bash
docker compose run --rm api alembic upgrade head
```

## Endpoints

```text
GET  /livez
GET  /readyz
GET  /healthz
GET  /api/v1/demo/hello/{name}
POST /api/v1/demo/greet
```

`/livez` only checks that the process is alive. `/readyz` and `/healthz` check PostgreSQL and Redis and return HTTP 503 when a dependency is unavailable.

## Database migrations

The application does not call `Base.metadata.create_all()` at startup. Schema changes are managed exclusively through Alembic:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```
