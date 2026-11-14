"""数据库连接。桌面版默认 SQLite（单文件），云端通过 GC_DB_URL 指向 PostgreSQL。"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator


def data_dir() -> Path:
    path = Path(os.environ.get("GC_DATA_DIR", Path.home() / ".gcpricing"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_url() -> str:
    return os.environ.get("GC_DB_URL") or f"sqlite:///{data_dir() / 'gcpricing.db'}"


class Base(DeclarativeBase):
    pass


class Dec(TypeDecorator):
    """Decimal 以字符串存储，避免 SQLite 把金额和工程量转成浮点数。"""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("不接受浮点数")
        return str(Decimal(str(value)))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


def make_engine(url: str | None = None):
    url = url or default_url()
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
