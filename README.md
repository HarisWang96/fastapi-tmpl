# FastAPI PostgreSQL + Redis Service Template

Minimal production-oriented FastAPI service template. It includes:

- FastAPI with async SQLAlchemy and PostgreSQL
- Async Redis client with connection pooling and timeouts
- Alembic migrations
- Liveness, readiness and dependency health checks
- A validated demo route
- Docker Compose for API, PostgreSQL and Redis
- Request IDs, structured logs, standard error responses and Prometheus metrics
- Gateway identity headers and service-side authorization client (fail closed)
- Async PostgreSQL idempotency and optional RabbitMQ transactional outbox

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

## Service foundation

- Middleware accepts a validated `X-Request-Id` or generates one, returns it in the response, and adds it to logs. Set `LOG_FORMAT=json` for structured JSON logs; set `LOG_TO_FILE=false` in containers.
- `/metrics` exports Prometheus counters/histograms with route-template labels. Set `METRICS_TOKEN` (required in production) and scrape with `X-Metrics-Token` or a Bearer token.
- Downstream identity comes from gateway headers (`X-User-Id`, `X-App-Id`). Set `TRUSTED_PROXY_TOKEN` when the gateway sends `X-Proxy-Token`; network policy is still required. Use `require_perm("catalog:read")` and `require_scope("catalog", "store")` from `app.dependencies` for service-side checks. Authorization errors fail closed.
- `@idempotent(required=True)` protects write handlers using `Idempotency-Key`. The async PostgreSQL store replays JSON and explicit `Response` bodies/status/headers. For ordinary returns with a non-200 route status, pass that status to the decorator, e.g. `@idempotent(status_code=201)`. Run the included Alembic migration before enabling it.
- RabbitMQ is optional and disabled by default. Set `EVENT_ENABLED=true` and `EVENT_BROKER_URL` to enable the async outbox relay. Call `await emit_event(db, "order.created", payload)` in the business `AsyncSession` transaction; register consumers with `@subscribe("order.created")`. `/readyz` includes RabbitMQ when enabled. Schema changes are managed through Alembic.

See `.env.example` for all service, security, observability and event settings. `APP_ENV=prod` requires the metrics and internal service tokens; use a separate secret for each deployment.

## Database migrations

The application does not call `Base.metadata.create_all()` at startup. Schema changes are managed exclusively through Alembic:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```
