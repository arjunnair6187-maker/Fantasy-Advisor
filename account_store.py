"""Tenant-scoped storage primitives for the hosted multi-user advisor.

Every private query requires both an authenticated user ID and, where relevant,
that user's league ID. Provider credentials are encrypted before persistence.
The app uses these records for owner-scoped league connections and private data.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import binascii
import json
import os
import uuid
from typing import Any, Iterator

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    inspect,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from db_urls import database_url_from_env


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ProviderConnection(Base):
    __tablename__ = "provider_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.user_id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    credentials_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    __table_args__ = (UniqueConstraint("user_id", "id", name="uq_provider_connection_owner_id"),)


class FantasyLeague(Base):
    __tablename__ = "fantasy_leagues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_connection_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider_league_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sport: Mapped[str] = mapped_column(String(8), nullable=False)
    season: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    scoring_settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    roster_settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["user_id"], ["app_users.user_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["user_id", "provider_connection_id"],
            ["provider_connections.user_id", "provider_connections.id"],
            ondelete="CASCADE",
            name="fk_league_owned_provider_connection",
        ),
        UniqueConstraint("user_id", "id", name="uq_league_owner_id"),
        UniqueConstraint(
            "user_id", "provider_connection_id", "provider_league_id", "sport", "season",
            name="uq_user_provider_league_season",
        ),
    )


class PrivateRecord(Base):
    """Flexible owner-scoped record for snapshots, forecasts, and decisions."""

    __tablename__ = "private_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    league_id: Mapped[str] = mapped_column(String(36), nullable=False)
    record_type: Mapped[str] = mapped_column(String(48), nullable=False)
    record_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "league_id"],
            ["fantasy_leagues.user_id", "fantasy_leagues.id"],
            ondelete="CASCADE",
            name="fk_private_record_owned_league",
        ),
        UniqueConstraint(
            "user_id", "league_id", "record_type", "record_key",
            name="uq_private_record_owner_key",
        ),
    )


@lru_cache(maxsize=1)
def _engine() -> Engine:
    url = database_url_from_env()
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


@lru_cache(maxsize=1)
def _sessions():
    return sessionmaker(bind=_engine(), expire_on_commit=False)


@contextmanager
def _session_scope() -> Iterator[Any]:
    session = _sessions()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_development_schema() -> None:
    """Create tables for local development; production should use migrations."""
    Base.metadata.create_all(_engine())


def verify_schema() -> None:
    """Confirm the pre-provisioned account tables exist without changing them."""
    required = set(Base.metadata.tables)
    existing = set(inspect(_engine()).get_table_names())
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(
            "Account storage schema is incomplete. Apply the database setup before enabling the app."
        )


def _cipher() -> Fernet:
    key = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must be configured to store provider credentials.")
    try:
        return Fernet(key.encode("ascii"))
    except (binascii.Error, ValueError, TypeError) as error:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key.") from error


def _owner(user_id: str) -> str:
    value = str(user_id or "").strip()
    if not value:
        raise ValueError("An authenticated user ID is required.")
    return value


def create_provider_connection(
    user_id: str,
    provider: str,
    credentials: dict[str, Any],
    label: str = "",
) -> str:
    """Create a connection owned by one user; never return credential data."""
    owner_id = _owner(user_id)
    provider_name = str(provider or "").strip().lower()
    if not provider_name:
        raise ValueError("A provider name is required.")
    if not isinstance(credentials, dict) or not credentials:
        raise ValueError("Provider credentials must be a non-empty object.")
    ciphertext = _cipher().encrypt(
        json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    connection_id = str(uuid.uuid4())
    with _session_scope() as session:
        if session.get(AppUser, owner_id) is None:
            session.add(AppUser(user_id=owner_id))
        session.add(ProviderConnection(
            id=connection_id,
            user_id=owner_id,
            provider=provider_name,
            label=str(label or "")[:120],
            credentials_ciphertext=ciphertext,
        ))
    return connection_id


def get_provider_connection(user_id: str, connection_id: str) -> dict[str, Any] | None:
    """Return connection metadata only when it belongs to the signed-in user."""
    owner_id = _owner(user_id)
    with _session_scope() as session:
        row = session.scalar(select(ProviderConnection).where(
            ProviderConnection.user_id == owner_id,
            ProviderConnection.id == str(connection_id),
        ))
        if row is None:
            return None
        return {
            "id": row.id,
            "provider": row.provider,
            "label": row.label,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


def list_provider_connections(user_id: str) -> list[dict[str, Any]]:
    """List only the signed-in user's provider connection metadata."""
    owner_id = _owner(user_id)
    with _session_scope() as session:
        rows = session.scalars(select(ProviderConnection).where(
            ProviderConnection.user_id == owner_id,
        ).order_by(ProviderConnection.created_at.desc()))
        return [{
            "id": row.id,
            "provider": row.provider,
            "label": row.label,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        } for row in rows]


def update_provider_credentials(
    user_id: str,
    connection_id: str,
    credentials: dict[str, Any],
) -> bool:
    """Replace credentials only on a connection owned by this user."""
    owner_id = _owner(user_id)
    if not isinstance(credentials, dict) or not credentials:
        raise ValueError("Provider credentials must be a non-empty object.")
    ciphertext = _cipher().encrypt(
        json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    with _session_scope() as session:
        row = session.scalar(select(ProviderConnection).where(
            ProviderConnection.user_id == owner_id,
            ProviderConnection.id == str(connection_id),
        ))
        if row is None:
            return False
        row.credentials_ciphertext = ciphertext
        row.status = "connected"
        row.updated_at = _utc_now()
        return True


def get_provider_credentials(user_id: str, connection_id: str) -> dict[str, Any]:
    """Decrypt credentials only after checking ownership of the connection."""
    owner_id = _owner(user_id)
    with _session_scope() as session:
        row = session.scalar(select(ProviderConnection).where(
            ProviderConnection.user_id == owner_id,
            ProviderConnection.id == str(connection_id),
        ))
        if row is None:
            raise LookupError("Provider connection not found for this user.")
        ciphertext = row.credentials_ciphertext
    try:
        clear = _cipher().decrypt(ciphertext)
        value = json.loads(clear.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Saved provider credentials could not be decrypted.") from error
    if not isinstance(value, dict):
        raise RuntimeError("Saved provider credentials have an invalid format.")
    return value


def disconnect_provider(user_id: str, connection_id: str) -> bool:
    """Delete only the signed-in user's connection and its dependent league data."""
    owner_id = _owner(user_id)
    with _session_scope() as session:
        result = session.execute(delete(ProviderConnection).where(
            ProviderConnection.user_id == owner_id,
            ProviderConnection.id == str(connection_id),
        ))
        return bool(result.rowcount)


def create_league(
    user_id: str,
    connection_id: str,
    provider_league_id: str,
    sport: str,
    season: int,
    name: str = "",
    scoring_settings: dict[str, Any] | None = None,
    roster_settings: dict[str, Any] | None = None,
) -> str:
    """Attach a league to a provider connection owned by the same user."""
    owner_id = _owner(user_id)
    normalized_sport = str(sport or "").strip().lower()
    if normalized_sport not in {"nba", "nfl"}:
        raise ValueError("sport must be 'nba' or 'nfl'.")
    provider_id = str(provider_league_id or "").strip()
    if not provider_id:
        raise ValueError("A provider league ID is required.")
    league_id = str(uuid.uuid4())
    with _session_scope() as session:
        connection = session.scalar(select(ProviderConnection).where(
            ProviderConnection.user_id == owner_id,
            ProviderConnection.id == str(connection_id),
        ))
        if connection is None:
            raise LookupError("Provider connection not found for this user.")
        session.add(FantasyLeague(
            id=league_id,
            user_id=owner_id,
            provider_connection_id=connection.id,
            provider_league_id=provider_id,
            sport=normalized_sport,
            season=int(season),
            name=str(name or "")[:200],
            scoring_settings=dict(scoring_settings or {}),
            roster_settings=dict(roster_settings or {}),
        ))
    return league_id


def list_leagues(user_id: str) -> list[dict[str, Any]]:
    """List only the signed-in user's leagues."""
    owner_id = _owner(user_id)
    with _session_scope() as session:
        rows = session.scalars(select(FantasyLeague).where(
            FantasyLeague.user_id == owner_id
        ).order_by(FantasyLeague.season.desc(), FantasyLeague.name))
        return [{
            "id": row.id,
            "provider_connection_id": row.provider_connection_id,
            "provider_league_id": row.provider_league_id,
            "sport": row.sport,
            "season": row.season,
            "name": row.name,
            "scoring_settings": row.scoring_settings,
            "roster_settings": row.roster_settings,
        } for row in rows]


def save_private_record(
    user_id: str,
    league_id: str,
    record_type: str,
    record_key: str,
    payload: dict[str, Any],
) -> None:
    """Insert or update a record only inside the owner's league boundary."""
    owner_id = _owner(user_id)
    kind = str(record_type or "").strip().lower()
    key = str(record_key or "").strip()
    if not kind or not key or not isinstance(payload, dict):
        raise ValueError("record_type, record_key, and an object payload are required.")
    with _session_scope() as session:
        league = session.scalar(select(FantasyLeague).where(
            FantasyLeague.user_id == owner_id,
            FantasyLeague.id == str(league_id),
        ))
        if league is None:
            raise LookupError("League not found for this user.")
        row = session.scalar(select(PrivateRecord).where(
            PrivateRecord.user_id == owner_id,
            PrivateRecord.league_id == league.id,
            PrivateRecord.record_type == kind,
            PrivateRecord.record_key == key,
        ))
        if row is None:
            session.add(PrivateRecord(
                id=str(uuid.uuid4()), user_id=owner_id, league_id=league.id,
                record_type=kind, record_key=key, payload=payload,
            ))
        else:
            row.payload = payload
            row.updated_at = _utc_now()


def get_private_record(
    user_id: str,
    league_id: str,
    record_type: str,
    record_key: str,
) -> dict[str, Any] | None:
    """Read one private record after checking both its owner and league."""
    owner_id = _owner(user_id)
    kind = str(record_type or "").strip().lower()
    key = str(record_key or "").strip()
    if not kind or not key:
        raise ValueError("record_type and record_key are required.")
    with _session_scope() as session:
        row = session.scalar(select(PrivateRecord).where(
            PrivateRecord.user_id == owner_id,
            PrivateRecord.league_id == str(league_id),
            PrivateRecord.record_type == kind,
            PrivateRecord.record_key == key,
        ))
        if row is None:
            return None
        return {
            "record_key": row.record_key,
            "payload": row.payload,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


def list_private_records(
    user_id: str,
    league_id: str,
    record_type: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read records only when both owner and league match."""
    owner_id = _owner(user_id)
    kind = str(record_type or "").strip().lower()
    if not kind:
        raise ValueError("record_type is required.")
    bounded_limit = max(1, min(int(limit), 500))
    with _session_scope() as session:
        rows = session.scalars(select(PrivateRecord).where(
            PrivateRecord.user_id == owner_id,
            PrivateRecord.league_id == str(league_id),
            PrivateRecord.record_type == kind,
        ).order_by(PrivateRecord.updated_at.desc()).limit(bounded_limit))
        return [{
            "record_key": row.record_key,
            "payload": row.payload,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        } for row in rows]
