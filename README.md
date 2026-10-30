# fastapi-svc — 微服务通用骨架

FastAPI + MySQL（SQLAlchemy 同步 ORM / 裸 SQL 共用一套池）+ Redis + Alembic。
**不含任何鉴权代码**：JWT 的签发与校验属于 auth 服务，下游服务只读网关注入的身份头。

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
│   │   ├── exceptions.py       # AppError 体系 + 全局 handler
│   │   ├── middleware.py       # 请求 ID + 访问日志（纯 ASGI）
│   │   ├── schemas/common.py   # 统一响应 {code,message,data,timestamp}
│   │   └── db/                 # orm / mysql（裸 SQL）/ redis
│   ├── api/
│   │   ├── deps.py             # get_db / get_session / get_redis / Caller
│   │   ├── router.py           # 唯一的路由聚合点
│   │   └── routes/             # health.py（三探针）、demo.py（冒烟）
│   ├── modules/_example/       # 示例域：api / service / repository / schemas
│   └── models/                 # ORM 模型（Base + 注册处）
├── alembic/                    # 迁移；env.py 复用 app.core.db.orm 的 Engine
├── tests/                      # pytest，不依赖外部 MySQL/Redis
├── Dockerfile                  # 多阶段 + 非 root + uvicorn supervisor
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
| `X-App-Id` | 调用方应用标识 | 同上为 `None` |
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

- 日志只出 stderr 由 K8s 采集（镜像内置 `LOG_TO_FILE=false`）：loguru 的锁与队列只在进程内生效，
  多 worker 共写同一文件时轮转/清理会互相踩
- 进程数由 `WEB_CONCURRENCY` 控制（默认 2）；`--timeout-graceful-shutdown 30`
  要求 K8s `terminationGracePeriodSeconds` ≥ 30
- 只有在入口代理可信网段内时才设置 `FORWARDED_ALLOW_IPS`，不要在不可信入站环境设为 `*`；
  默认仅信任 loopback 转发头
- 探针：livenessProbe 只打 `/livez`；readinessProbe 打 `/readyz`。
  `/readyz` 会探 MySQL/Redis，依赖抖动时回 503——配成 liveness 会触发全量重启
- `MYSQL_POOL_MAX_CONNECTIONS` 是**单进程**上限，实际连接数 = 该值 × `WEB_CONCURRENCY` × 副本数
- 端口由 `PORT` 控制（镜像默认 8000），按服务改 Dockerfile 的 `EXPOSE` 与 K8s Service
- CI 沿用现有 Jenkinsfile / K8s 清单；本仓库不含它们

## 剥离示例（接入真实业务时）

删掉这三处即可，它们不参与框架能力：

1. `app/modules/_example/`
2. `app/api/routes/demo.py` 以及 `app/api/router.py` 里对它的引用
3. `tests/` 里针对 demo 的断言（`test_caller.py` / `test_contract.py` 中路径同步替换）

完成后验收：

```bash
# 骨架里不应有任何 JWT 相关 import 或依赖（docstring 里出现的 "JWT" 是说明文字，不算）
grep -rnE --include='*.py' "import jwt|import argon2|PyJWT|argon2_cffi" app/
grep -nE "pyjwt|argon2" pyproject.toml
uv run pytest -q && uv run ruff check app tests alembic && uv run ruff format --check app tests alembic
```
