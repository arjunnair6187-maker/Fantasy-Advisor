"""Database URL handling shared by the app and Alembic migrations."""

from __future__ import annotations

import os


def database_url_from_env() -> str:
    """Return DATABASE_URL using the installed PostgreSQL driver when needed."""
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL must be configured before using account storage.")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url
