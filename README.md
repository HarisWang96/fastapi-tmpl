# fastapi-svc — 微服务通用骨架

FastAPI + MySQL（SQLAlchemy 同步 ORM / 裸 SQL 共用一套池）+ Redis + Alembic。
**不做认证**：JWT 的签发与校验属于 identity-svc，下游服务只读网关注入的身份头。
**权限判定在服务侧**：路由声明权限码，服务调 authz-svc（PDP）判定并做数据范围过滤；
网关只负责认证和路由级准入，不做逐接口权限判定。

新服务从本仓库 clone 后，替换 `APP_NAME`、删掉示例域，即可开始写业务。

## 目录

```
.
├── app/
│   ├── main.py                 # create_app：lifespan / CORS / 异常注册 / 路由挂载
│   ├── core/
│   │   ├── config.py           # pydantic-settings，全部配置来自环境变量/.env
│   │   ├── clock.py            # 业务时间：按 TIMEZONE 取 naive 本地时间
│   │   ├── logger.py           # loguru + stdlib 桥接，容器内只出 stderr
│   │   ├── context.py          # request_id ContextVar（跨线程传递）
│   │   ├── metrics.py          # Prometheus 指标 + /metrics 令牌门禁
│   │   ├── exceptions.py       # AppError 体系 + 全局 handler
│   │   ├── middleware.py       # 请求 ID + 访问日志 + HTTP 指标（纯 ASGI）
│   │   ├── schemas/common.py   # 统一响应 {code,message,data,timestamp}
│   │   └── db/                 # orm / mysql（裸 SQL）/ redis
│   ├── api/
│   │   ├── deps.py             # get_db / get_session / get_redis / Caller
│   │   ├── authz_deps.py       # require_perm / require_scope + 本地 TTL 缓存
│   │   ├── router.py           # 唯一的路由聚合点
│   │   └── routes/             # health.py（三探针）、demo.py（冒烟）
│   ├── clients/authz.py        # authz-svc PDP 客户端
│   ├── modules/_example/       # 示例域：api / service / repository / schemas
│   └── models/                 # ORM 模型（Base + 注册处）
├── alembic/                    # 迁移；env.py 复用 app.core.db.orm 的 Engine
├── tests/                      # pytest，不依赖外部 MySQL/Redis
├── Dockerfile                  # 多阶段 + 非 root + 单进程 uvicorn
└── .env.example
```

## 快速开始

```bash
cp .env.example .env                                   # 填入真实连接信息
uv sync                                                # 建 .venv 并按 uv.lock 安装
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q
uv run ruff check app tests alembic
uv run ruff format --check app tests alembic

# 有真实 MySQL 时跑集成测试（默认跳过，读 .env 里 MYSQL_DATABASES.default）
RUN_MYSQL_TESTS=1 uv run pytest -q tests/test_mysql_integration.py
```

- 文档：`/docs`（`APP_ENV=dev` 或 `DEBUG=true` 才开；不配 .env 时按 prod 处理，文档关闭）
- 验证：`GET /livez`、`GET /readyz`、`GET /api/v1/demo/ping`、`GET /api/v1/demo/me`

## 身份传递（网关 → 下游）

| 请求头 | 含义 | 缺失时 |
|---|---|---|
| `X-User-Id` | 调用者用户 ID（整数） | `CallerDep` 返回 `None`；`RequiredCallerDep` 返回 401 |
| `X-App-Id` | 网关从 access token 的 `app_id` 声明注入的应用标识 | 同上为 `None` |
| `X-Proxy-Token` | 可选代理令牌 | 配置了 `TRUSTED_PROXY_TOKEN` 才校验，否则忽略 |

```python
from app.api.deps import CallerDep, RequiredCallerDep

@router.get("/orders")
def list_orders(caller: CallerDep): ...            # 公开接口，也能知道是谁调的

@router.post("/orders")
def create_order(caller: RequiredCallerDep): ...   # 必须有身份，否则 401
```

**这些头可被任意请求伪造。** 信任边界必须由 NetworkPolicy 保证（只允许网关命名空间入站），
`TRUSTED_PROXY_TOKEN` 在 `APP_ENV=prod` 时必填，并由服务逐请求校验；它仍不能替代网络策略。
网关必须配置相同的密钥。开发/测试环境可以不设置。

## 权限判定（服务侧）

| 层 | 职责 |
|---|---|
| 网关 | JWT 验签、注入 `X-User-Id` / `X-App-Id`、公开接口 allowlist、路由级准入（public / jwt） |
| 服务（本骨架） | 路由声明的权限码、调 authz-svc 判定、数据范围过滤、资源归属校验 |
| authz-svc | PDP：权限点、角色、显式拒绝、数据范围、判定版本 |

细粒度权限不能只放网关：网关看不到资源归属，内部调用/定时任务/导出也不经过网关。

```python
from typing import Annotated

from fastapi import Depends

from app.api.authz_deps import require_perm, require_scope
from app.api.deps import Caller
from app.clients.authz import DataScope

@router.get("/products")
async def list_products(
    caller: Annotated[Caller, Depends(require_perm("product:read"))],
    scope: Annotated[DataScope, Depends(require_scope("product", "store"))],
):
    # scope.filter_values(): None = 不过滤（ALL），[] = 无可见数据（NONE），
    # 其余为 IN 值列表；把这些值用 %s 绑定进 WHERE，不要拼字符串。
    ...
```

- 新接口必须显式声明权限码；`check_api` 的路径映射只用于迁移旧接口兜底。
- 权限服务不可用或响应异常时 **fail closed**，返回 503，不会放行。
- 判定结果在进程内缓存 `AUTHZ_CACHE_TTL_SECONDS`（默认 30 秒），
  这是权限撤销/停用的最大延迟；设为 `0` 可关闭缓存、每次实时判定。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `AUTHZ_BASE_URL` | `http://authz-svc:8000` | authz-svc 地址 |
| `AUTHZ_TIMEOUT_SECONDS` | `3` | 调用超时 |
| `AUTHZ_CACHE_TTL_SECONDS` | `30` | 本地判定缓存，0 为关闭 |
| `INTERNAL_API_TOKEN` | 无 | 服务间令牌，必须与 authz-svc 一致；prod 必填 |
| `METRICS_TOKEN` | 无 | `/metrics` 访问令牌；prod 必填，也建议限制抓取来源网络 |

## 幂等与事件

**幂等（写接口防重复提交）**

```python
from fastapi import Request
from app.core.idempotency import idempotent

@router.post("/orders")
    @idempotent(required=True)          # request: Request 必须出现在签名里
def create_order(request: Request, ...): ...
```

- 客户端带 `Idempotency-Key`；首次执行并存储响应，重放返回同一响应，不重复写库。
  若端点返回普通数据但声明了非 200 状态码，用 `@idempotent(status_code=201)` 同步声明；
  显式 `Response` 会保留状态码、响应体和响应头（不重放 request ID 等逐请求头）
- 同 key 不同请求体 → 409；同 key 并发未完成 → 409；处理异常会释放 key 供重试
- 存储表 `sys_idempotency`，按 `scope`（app/user/method/path）隔离，默认保留 24 小时
- `required=False`（默认）时没有请求头就按普通请求执行，适合渐进接入

**事件（transactional outbox + RabbitMQ）**

```python
from app.core.events import emit_event, subscribe

# 与业务写入同一个事务：commit 后事件才可能被投递
emit_event(session, "order.created", {"order_id": order_id})

@subscribe("order.created")
def on_order_created(payload: dict, headers: dict) -> None: ...
```

- `emit_event` 只写 `sys_outbox`，不直接发 MQ；relay 后台任务负责发布并标记
- 交换器 `EVENT_EXCHANGE`（topic、持久化）；消费队列每服务一个，绑定 `@subscribe` 的 topic
- 投递语义为 **at-least-once**：消费成功后写 `sys_event_consumed` 去重；
  handler 有外部副作用时必须自身幂等
- 消费失败按 `CONSUMER_MAX_RETRIES` 退避重试，仍失败转死信队列 `<queue>.dlq`
- `EVENT_ENABLED=false`（默认）时完全不连 broker；开启时必须配置 `EVENT_BROKER_URL`

## 契约约定

1. 业务代码只 `raise AppError(...)`，不要自己拼错误响应
2. SQL 只写在 `modules/<domain>/repository.py`，用户输入一律 `%s` 占位符
3. 外部依赖（DB/Redis）由接口通过 `DbSession` / `SessionDep` / `RedisClient` 注入，
   service 层只接收参数，不自己取连接
4. 分页/查询参数用 `Annotated[..., Query(ge=..., le=...)]` 声明，非法参数自动 422
5. **写操作必须在 handler 返回前显式 `commit()`**：依赖里的 commit 执行在响应发出**之后**，
   失败时客户端已经拿到 200，那一行只能兜底
6. 业务时间统一用 `app.core.clock.now()`，不要直接 `datetime.now()`：
   库里 DATETIME 是 naive 本地时间，口径由 `TIMEZONE`（默认 `Asia/Shanghai`）决定，与容器 TZ 无关
7. 需要权限的接口用 `require_perm(...)` / `require_scope(...)` 声明，不在 handler 内手写权限判断；
   未声明权限的接口默认只受网关的登录态约束

## 数据访问

- **一个库一套池**：ORM 与裸 SQL 共用 `app/core/db/orm.py` 的同一个 Engine，
  单进程上限 = `MYSQL_POOL_MAX_CONNECTIONS`（`max_overflow=0`）
- **驱动**：`PyMySQL[rsa]`（`mysql+pymysql`），不依赖 libmysqlclient
- **MySQL 超时**：`MYSQL_CONNECT_TIMEOUT` 限制建连时间，`MYSQL_READ_TIMEOUT` / `MYSQL_WRITE_TIMEOUT`
  限制驱动 socket 读写等待（默认分别为 5/30/30 秒）；它们不是 SQL 执行总时限，慢查询仍应通过数据库侧策略控制
- **ORM**：`SessionDep` → `session.get/scalars`
- **裸 SQL**：`DbSession` → `MysqlConnection`，`exec_driver_sql`，行统一转 dict
- **字面 `%` 必须写成 `%%`**：`exec_driver_sql` 走 PyMySQL 的 format 参数风格，
  带参执行时 SQL 里单个 `%`（如 `DATE_FORMAT(x, '%Y')`）会在驱动内炸；`MysqlConnection`
  执行前会拦下并报 `ValueError`，正确写法是 `DATE_FORMAT(x, '%%Y')`
- **Redis**：`get_redis(instance, db)` 按 `(实例, db)` 懒建池，`decode_responses=True`
- **探针**：`READINESS_DEPENDENCIES` 声明 readiness 必需依赖（`mysql`、`redis` 的子集，可设 `[]`），
  只有列出的依赖会影响 `/readyz`；liveness 始终只检查进程
- **ClickHouse 等其它数据源不在骨架内**：需要它的服务自行加 `core/db/<name>.py` 与配置项

## 迁移（Alembic）

```bash
# 1. 在 app/models/ 定义模型，并在 app/models/__init__.py 里 import 注册
# 2. 生成迁移（需要能连上库里配置的 default 连接）
uv run alembic revision --autogenerate -m "add orders"
# 3. 检查生成的脚本（尤其 DROP / 列类型），再应用
uv run alembic upgrade head
```

`env.py` 有一道安全阀：`Base.metadata` 为空时拒绝 autogenerate，
避免把库里已有的表全部生成为 DROP。

## 部署

- 日志只出 stderr 由容器平台采集（镜像内置 `LOG_TO_FILE=false`）；
  `LOG_FORMAT=json` 时每行一条 JSON（自动带 `service` 与 `request_id`），
  `text` 保留人类可读格式
- `/metrics` 暴露 Prometheus 指标（`http_requests_total` / `http_request_duration_seconds`），
  path 标签用路由模板而非原始 URL；配置 `METRICS_TOKEN` 后需带 `X-Metrics-Token`
  或 Bearer；生产启动时必须配置该令牌。业务指标在各自模块定义 Counter，在 `/metrics` 一并输出
- `EVENT_ENABLED=true` 时，`/readyz` 会检查 RabbitMQ 发布连接是否就绪；broker 不可用会返回 503
- 容器内固定单进程，扩容交给 Deployment 副本数；不要再加 `--workers`，
  否则会和 HPA 形成两个互不相知的扩缩容维度。`--timeout-graceful-shutdown 30`
  要求 K8s `terminationGracePeriodSeconds` ≥ 30
- 单进程 pod 的 `requests.cpu` 不应超过 1 核：单进程最多吃满一核，
  requests 设成 2 时 HPA 按 CPU 永远不会触发
- 只有在入口代理可信网段内时才设置 `FORWARDED_ALLOW_IPS`，不要在不可信入站环境设为 `*`；
  默认仅信任 loopback 转发头
- 探针：livenessProbe 只打 `/livez`；readinessProbe 打 `/readyz`。
  `/readyz` 会探 MySQL/Redis，依赖抖动时回 503——配成 liveness 会触发全量重启
- `MYSQL_POOL_MAX_CONNECTIONS` 是**单进程单库**上限，总连接数 =
  该值 × 库数 × 副本数；还要给迁移 Job、探针和监控留余量
- 端口由 `PORT` 控制（镜像默认 8000），按服务改 Dockerfile 的 `EXPOSE` 与 K8s Service
- CI 沿用现有 Jenkinsfile / K8s 清单；本仓库不含它们

## 剥离示例（接入真实业务时）

删掉这三处即可，它们不参与框架能力：

1. `app/modules/_example/`
2. `app/api/routes/demo.py` 以及 `app/api/router.py` 里对它的引用
3. `tests/` 里针对 demo 的断言（`test_caller.py` / `test_contract.py` / `test_authz.py` 中路径同步替换）

完成后验收：

```bash
# 骨架里不应有任何 JWT 相关 import 或依赖（docstring 里出现的 "JWT" 是说明文字，不算）
grep -rnE --include='*.py' "import jwt|import argon2|PyJWT|argon2_cffi" app/
grep -nE "pyjwt|argon2" pyproject.toml
uv run pytest -q && uv run ruff check app tests alembic && uv run ruff format --check app tests alembic
```
