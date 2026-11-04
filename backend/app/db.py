"""Database engine, session factory and a pgvector-or-JSON embedding column type."""
from collections.abc import Generator

from sqlalchemy import JSON, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import get_settings

EMBEDDING_DIM = 384

settings = get_settings()
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Embedding(TypeDecorator):
    """Stores vectors in pgvector on PostgreSQL and as JSON elsewhere (SQLite in tests)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        vec = [float(v) for v in value][:EMBEDDING_DIM]
        vec += [0.0] * (EMBEDDING_DIM - len(vec))
        return vec

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
