"""Alembic environment reusing the synchronous Engine from app.core.db.orm.

Safety check: refuse autogenerate when Base.metadata is empty. Otherwise,
Alembic may consider every existing database table a drop candidate.
"""

from logging.config import fileConfig

from alembic import context
from app.core.config import settings
from app.core.db.orm import build_url, get_engine
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url():
    cfg = settings.MYSQL_DATABASES.get("default")
    if cfg is None:
        raise RuntimeError("MYSQL_DATABASES 未配置 default，无法执行迁移")
    return build_url(cfg).render_as_string(hide_password=False)


def _refuse_empty_autogenerate() -> None:
    opts = config.cmd_opts
    if opts is not None and getattr(opts, "autogenerate", False) and not target_metadata.tables:
        raise RuntimeError(
            "Base.metadata 为空：先在 app/models/ 定义模型并在 app/models/__init__.py 注册，"
            "再执行 autogenerate，否则会生成删除所有表的迁移"
        )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with get_engine("default").connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


_refuse_empty_autogenerate()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
