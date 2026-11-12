# FastAPI PostgreSQL + Redis Service Template

Minimal production-oriented FastAPI service template. It includes:

- FastAPI with async SQLAlchemy and PostgreSQL
- Optional async Redis client with connection pooling and timeouts
- Alembic migrations
- Liveness, readiness and dependency health checks
- A validated demo route
- Docker Compose for API, PostgreSQL and Redis
- Request IDs, structured logs, standard error responses and Prometheus metrics
- Gateway identity headers and service-side authorization client (fail closed)
- Async PostgreSQL idempotency and optional RabbitMQ transactional outbox
- A complete example order workflow (API, schema, database model and outbox event)
- Optional OpenTelemetry tracing with W3C context propagation over HTTPX

## Run locally

```bash
uv sync
cp .env.example .env
uv run alembic upgrade head
./scripts/start.sh
```

This is the shortest useful path: PostgreSQL is required; Redis and RabbitMQ are optional and disabled by default. The included `/api/v1/orders` example demonstrates validation, a business service layer, persistence, an outbox event, and idempotency. Try it with:

```bash
curl -X POST http://localhost:8000/api/v1/orders \\
  -H 'Content-Type: application/json' -H 'Idempotency-Key: order-demo-1' \\
  -d '{"customer_id":"customer-1","sku":"sku-1","quantity":2}'
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

## Local production-like smoke test

The isolated `prod-sim` profile starts the application with `APP_ENV=prod`, local-only test tokens, and temporary data stores. It exercises PostgreSQL migrations, Redis readiness, RabbitMQ outbox delivery, authorization HTTP calls, and OTLP trace export. It does not reuse the development database volume:

```bash
docker compose --profile prod-sim run --rm prod-sim-api alembic upgrade head
docker compose --profile prod-sim up -d --build prod-sim-api
curl -fsS http://localhost:18000/readyz
curl -fsS -H 'X-Metrics-Token: local-only-metrics-test-token' http://localhost:18000/metrics
curl -fsS http://localhost:18000/api/v1/demo/protected \
  -H 'X-User-Id: 7' -H 'X-App-Id: local-test' -H 'X-Proxy-Token: local-only-proxy-test-token'
curl -fsS http://localhost:18000/api/v1/demo/protected-scope \
  -H 'X-User-Id: 7' -H 'X-App-Id: local-test' -H 'X-Proxy-Token: local-only-proxy-test-token'
curl -i -X POST http://localhost:18000/api/v1/orders \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: prod-sim-order-1' \
  -d '{"customer_id":"customer-1","sku":"sku-1","quantity":2}'
docker compose --profile prod-sim down
```

Run the full automated production-simulation smoke check (it starts and then removes only this isolated profile):

```bash
bash tests/smoke_prod_sim.sh
```

After creating an order, verify the outbox event reached `published` and `sys_event_consumed`, and that the OTLP receiver reports a non-zero payload:

```bash
docker compose --profile prod-sim exec prod-sim-db psql -U prod_sim -d fastapi_prod_sim \
  -c 'select status, count(*) from public.sys_outbox group by status'
docker compose --profile prod-sim exec prod-sim-db psql -U prod_sim -d fastapi_prod_sim \
  -c 'select count(*) from public.sys_event_consumed'
docker compose --profile prod-sim exec prod-sim-otel python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:4318/stats').read().decode())"
```

The production application container runs as a non-root user. These credentials and mock services are for local simulation only and must never be reused in a real deployment.

## Endpoints

```text
GET  /livez
GET  /readyz
GET  /healthz
GET  /api/v1/demo/hello/{name}
POST /api/v1/demo/greet
```

`/livez` only checks that the process is alive. `/readyz` and `/healthz` check PostgreSQL and enabled optional dependencies, returning HTTP 503 when one is unavailable. Redis is disabled by default; set `REDIS_ENABLED=true` when the service uses it. Docker Compose enables Redis for local development.

## Service foundation

- Middleware accepts a validated `X-Request-Id` or generates one, returns it in the response, and adds it to logs. Set `LOG_FORMAT=json` for structured JSON logs; set `LOG_TO_FILE=false` in containers.
- `/metrics` exports Prometheus counters/histograms with route-template labels. Set `METRICS_TOKEN` (required in production) and scrape with `X-Metrics-Token` or a Bearer token.
- Set `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` to export traces. FastAPI server spans and HTTPX client spans propagate W3C `traceparent`/`tracestate`; set `OTEL_EXPORTER_OTLP_HEADERS` to comma-separated OTLP headers when required. Tracing is off by default.
- Downstream identity comes from gateway headers (`X-User-Id`, `X-App-Id`). Set `AUTH_ENABLED=true` and `TRUSTED_PROXY_TOKEN` to use identity dependencies; the token is required whenever this feature is enabled. Network policy is still required. Set `AUTHZ_ENABLED=true` and `INTERNAL_API_TOKEN` to use `require_perm("catalog:read")` and `require_scope("catalog", "store")` from `app.dependencies`. Authorization errors fail closed.
- `@idempotent(required=True)` protects write handlers using `Idempotency-Key`. The decorated endpoint must accept `request: Request` and `db: AsyncSession`; the decorator owns that session's transaction, so the handler must not call `begin()`, `commit()` or `rollback()`. Business changes and the replayable response record commit atomically. It replays JSON and explicit `Response` bodies/status/headers. For ordinary returns with a non-200 route status, pass that status to the decorator, e.g. `@idempotent(status_code=201)`. Run the included Alembic migration before enabling it.
- RabbitMQ is optional and disabled by default. Set `EVENT_ENABLED=true` and `EVENT_BROKER_URL` to enable the async outbox relay. Call `await emit_event(db, "order.created", payload)` in the business `AsyncSession` transaction. Consumers register with `@subscribe("order.created")`; handlers receive `(session, payload, headers)` and must use the provided `AsyncSession` without committing it, so local database changes and the consumed-event record share one transaction. Delivery remains at-least-once across broker/database boundaries, so external side effects still need idempotency. Failures are retried with bounded exponential delay, then routed to a durable `<queue>.dead` queue via `EVENT_DLX_EXCHANGE`. `/readyz` includes RabbitMQ when enabled. Schema changes are managed through Alembic.

See `.env.example` for service, security, observability and event settings. `APP_ENV=prod` requires `METRICS_TOKEN`; enabled identity and authorization integrations require their own tokens in every environment. Use separate secrets for each deployment.

## Development checks

```bash
uv sync --extra test --extra dev
uv run pytest -m 'not integration'
uv run ruff check .
```

## Project layout

- `app/` contains application runtime code: routers, schemas, models, services and infrastructure integrations.
- `alembic/` contains database migrations.
- `tests/` contains unit/integration tests and local-only support services for the production simulation. This directory is excluded from the application image.
- `scripts/` contains developer utilities such as local startup and database reset; it is also excluded from the image.
- `.github/workflows/` contains CI workflows and is not part of the runtime image.

Database-backed integration tests need Docker and PostgreSQL. Run the `test-db` service, apply migrations, then run the marked tests:

```bash
docker compose --profile test up -d --wait test-db
DATABASE_URL=postgresql+asyncpg://test:test@localhost:55432/fastapi_test uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://test:test@localhost:55432/fastapi_test uv run pytest -m integration
docker compose --profile test stop test-db
```

CI runs lint and database-independent tests separately from PostgreSQL integration tests. Add service-owned routes under `app/routers`, contracts under `app/schemas`, persistence models under `app/models`, and business operations under `app/services`; add an Alembic revision for each schema change.

## Database migrations

The application does not call `Base.metadata.create_all()` at startup. Schema changes are managed exclusively through Alembic:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```
