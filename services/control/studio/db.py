from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from sqlalchemy import create_engine, event, String, DateTime, ForeignKey, UniqueConstraint, MetaData
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(schema="voice_studio" if settings.database_url.startswith("postgresql") else None)


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Tenant(Entity):
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)


engine = create_engine(
    settings.database_url,
    # Supabase transaction pooling can move a client between server sessions.
    # Psycopg's automatic prepared statements must not retain session state.
    connect_args={"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {"options": "-c timezone=UTC", "prepare_threshold": None, "connect_timeout": 10},
    **({"pool_size": settings.database_pool_size, "max_overflow": settings.database_max_overflow, "pool_timeout": 10, "pool_recycle": 300} if not settings.database_url.startswith("sqlite") else {}),
    pool_pre_ping=True,
    hide_parameters=True,
)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_config(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(write=False):
    with SessionLocal() as db:
        try:
            if write and engine.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def as_dict(entity) -> dict[str, Any]:
    output = {}
    for col in entity.__table__.columns:
        value = getattr(entity, col.name)
        if isinstance(value, datetime):
            value = value.replace(tzinfo=timezone.utc).isoformat()
        output[col.name] = value
    return output


def tenant_unique():
    return UniqueConstraint("workspace_id", "id")
