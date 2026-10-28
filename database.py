"""Local SQLite storage for daily lineup snapshots."""

import sqlite3
from datetime import datetime
import json
import math
import uuid
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from account_store import (
    get_private_record,
    list_private_records,
    save_private_record,
)


DATABASE_PATH = Path(__file__).with_name("fantasy_advisor.db")
_TENANT_SCOPE: ContextVar[tuple[str, str] | None] = ContextVar(
    "fantasy_advisor_tenant_scope", default=None
)
_TENANT_REQUIRED = True


def set_tenant_required(required: bool = True) -> None:
    """Fail closed instead of falling back to the old shared SQLite store."""
    global _TENANT_REQUIRED
    _TENANT_REQUIRED = bool(required)


def set_tenant_scope(user_id: str, league_id: str) -> None:
    """Set the per-session owner and league for legacy-compatible data calls."""
    owner_id = str(user_id or "").strip()
    owned_league_id = str(league_id or "").strip()
    if not owner_id or not owned_league_id:
        raise ValueError("Both the authenticated user and owned league are required.")
    _TENANT_SCOPE.set((owner_id, owned_league_id))


@contextmanager
def tenant_scope(user_id: str, league_id: str) -> Iterator[None]:
    """Set and restore a tenant scope for one background task."""
    owner_id = str(user_id or "").strip()
    owned_league_id = str(league_id or "").strip()
    if not owner_id or not owned_league_id:
        raise ValueError("Both the authenticated user and owned league are required.")
    token = _TENANT_SCOPE.set((owner_id, owned_league_id))
    try:
        yield
    finally:
        _TENANT_SCOPE.reset(token)


def _current_scope() -> tuple[str, str] | None:
    scope = _TENANT_SCOPE.get()
    if scope is None and _TENANT_REQUIRED:
        raise RuntimeError("An authenticated user and owned league scope are required.")
    return scope


def _key(*parts) -> str:
    return json.dumps([str(part) for part in parts], ensure_ascii=False, separators=(",", ":"))


def _json_value(value):
    """Convert pandas/numpy scalars and timestamps into JSON-safe primitives."""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _save_scoped(record_type: str, record_key: str, payload: dict) -> None:
    scope = _current_scope()
    if scope is None:
        raise RuntimeError("A tenant storage write cannot use the shared database.")
    save_private_record(scope[0], scope[1], record_type, record_key, _json_value(payload))


def _list_scoped(record_type: str, limit: int = 500) -> list[dict]:
    scope = _current_scope()
    if scope is None:
        raise RuntimeError("A tenant storage read cannot use the shared database.")
    return list_private_records(scope[0], scope[1], record_type, limit=limit)


def _get_scoped(record_type: str, record_key: str) -> dict | None:
    scope = _current_scope()
    if scope is None:
        raise RuntimeError("A tenant storage read cannot use the shared database.")
    return get_private_record(scope[0], scope[1], record_type, record_key)


def initialize_database():
    """Create the snapshot table if it does not already exist."""

    if _current_scope() is not None:
        return

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                fantasy_team TEXT NOT NULL,
                player_name TEXT NOT NULL,
                nba_team TEXT,
                positions TEXT,
                injury_status TEXT,
                has_game_today INTEGER NOT NULL,
                fp_last_7 REAL,
                fp_last_14 REAL,
                fp_last_30 REAL,
                recommendation TEXT,
                reason TEXT,
                saved_at TEXT NOT NULL,
                UNIQUE(snapshot_date, fantasy_team, player_name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS matchup_forecasts (
                fantasy_season INTEGER NOT NULL,
                matchup_period INTEGER NOT NULL,
                fantasy_team TEXT NOT NULL,
                opponent TEXT NOT NULL,
                team_projection REAL NOT NULL,
                opponent_projection REAL NOT NULL,
                saved_at TEXT NOT NULL,
                PRIMARY KEY (fantasy_season, matchup_period, fantasy_team)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS power_snapshots (
                snapshot_week INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                rank INTEGER NOT NULL,
                power_score REAL NOT NULL,
                saved_at TEXT NOT NULL,
                PRIMARY KEY (snapshot_week, team_name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS move_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fantasy_team TEXT NOT NULL,
                add_player TEXT NOT NULL,
                drop_player TEXT NOT NULL,
                one_week_change REAL,
                two_week_change REAL,
                four_week_change REAL,
                season_fppg_change REAL,
                status TEXT NOT NULL DEFAULT 'Pending',
                notes TEXT,
                saved_at TEXT NOT NULL,
                decided_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_results (
                fantasy_season INTEGER NOT NULL,
                matchup_period INTEGER NOT NULL,
                fantasy_team TEXT NOT NULL,
                opponent TEXT NOT NULL,
                team_score REAL NOT NULL,
                opponent_score REAL NOT NULL,
                result TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                PRIMARY KEY (fantasy_season, matchup_period, fantasy_team)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS intelligence_evidence (
                evidence_hash TEXT PRIMARY KEY,
                collected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_briefings (
                evidence_hash TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                briefing_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_hash TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def save_daily_snapshot(snapshot_date, fantasy_team, rows):
    """Insert or update one team's daily player snapshots."""

    scope = _current_scope()
    if scope is not None:
        saved_at = datetime.now().isoformat(timespec="seconds")
        for row in rows:
            player_name = str(row["Player"])
            _save_scoped("daily_snapshot", _key(snapshot_date, fantasy_team, player_name), {
                "snapshot_date": str(snapshot_date),
                "fantasy_team": str(fantasy_team),
                "player_name": player_name,
                "nba_team": row.get("NBA team"),
                "positions": row.get("Positions"),
                "injury_status": row.get("Injury status"),
                "has_game_today": row.get("Game today"),
                "fp_last_7": row.get("FP last 7"),
                "fp_last_14": row.get("FP last 14"),
                "fp_last_30": row.get("FP last 30"),
                "recommendation": row.get("Recommendation"),
                "reason": row.get("Reason"),
                "saved_at": saved_at,
            })
        return

    saved_at = datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(DATABASE_PATH) as connection:
        for row in rows:
            connection.execute(
                """
                INSERT INTO daily_snapshots (
                    snapshot_date,
                    fantasy_team,
                    player_name,
                    nba_team,
                    positions,
                    injury_status,
                    has_game_today,
                    fp_last_7,
                    fp_last_14,
                    fp_last_30,
                    recommendation,
                    reason,
                    saved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    snapshot_date,
                    fantasy_team,
                    player_name
                )
                DO UPDATE SET
                    nba_team = excluded.nba_team,
                    positions = excluded.positions,
                    injury_status = excluded.injury_status,
                    has_game_today = excluded.has_game_today,
                    fp_last_7 = excluded.fp_last_7,
                    fp_last_14 = excluded.fp_last_14,
                    fp_last_30 = excluded.fp_last_30,
                    recommendation = excluded.recommendation,
                    reason = excluded.reason,
                    saved_at = excluded.saved_at
                """,
                (
                    str(snapshot_date),
                    fantasy_team,
                    row["Player"],
                    row["NBA team"],
                    row["Positions"],
                    row["Injury status"],
                    int(row["Game today"]),
                    row["FP last 7"],
                    row["FP last 14"],
                    row["FP last 30"],
                    row["Recommendation"],
                    row["Reason"],
                    saved_at,
                ),
            )


def snapshot_history(fantasy_team, limit=200):
    """Return recent saved recommendations for trend review."""
    initialize_database()
    if _current_scope() is not None:
        records = [item["payload"] for item in _list_scoped("daily_snapshot")]
        records = [row for row in records if row.get("fantasy_team") == str(fantasy_team)]
        records.sort(key=lambda row: (row.get("snapshot_date", ""), row.get("player_name", "")), reverse=True)
        fields = ("snapshot_date", "player_name", "fp_last_7", "fp_last_14", "fp_last_30", "recommendation", "reason", "saved_at")
        return [{field: row.get(field) for field in fields} for row in records[:max(1, int(limit))]]
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        records = connection.execute(
            """
            SELECT snapshot_date, player_name, fp_last_7, fp_last_14,
                   fp_last_30, recommendation, reason, saved_at
            FROM daily_snapshots
            WHERE fantasy_team = ?
            ORDER BY snapshot_date DESC, player_name
            LIMIT ?
            """,
            (fantasy_team, limit),
        ).fetchall()
    return [dict(record) for record in records]


def save_matchup_forecasts(season, fantasy_team, frame):
    """Preserve the earliest forecast for later accuracy measurement."""
    initialize_database()
    saved_at = datetime.now().isoformat(timespec="seconds")
    if _current_scope() is not None:
        for _, row in frame.iterrows():
            week = int(row["Fantasy week"])
            _save_scoped("matchup_forecast", _key(season, week, fantasy_team), {
                "fantasy_season": int(season),
                "matchup_period": week,
                "fantasy_team": str(fantasy_team),
                "opponent": row["Opponent"],
                "team_projection": row["Your projection"],
                "opponent_projection": row["Opponent projection"],
                "saved_at": saved_at,
            })
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        for _, row in frame.iterrows():
            connection.execute(
                """INSERT OR IGNORE INTO matchup_forecasts
                   (fantasy_season, matchup_period, fantasy_team, opponent,
                    team_projection, opponent_projection, saved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (season, int(row["Fantasy week"]), fantasy_team, row["Opponent"],
                 float(row["Your projection"]), float(row["Opponent projection"]), saved_at),
            )


def forecast_history(season, fantasy_team):
    initialize_database()
    if _current_scope() is not None:
        records = [item["payload"] for item in _list_scoped("matchup_forecast")]
        records = [row for row in records if row.get("fantasy_season") == int(season) and row.get("fantasy_team") == str(fantasy_team)]
        records.sort(key=lambda row: row.get("matchup_period", 0))
        return records
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT * FROM matchup_forecasts
               WHERE fantasy_season=? AND fantasy_team=? ORDER BY matchup_period""",
            (season, fantasy_team),
        ).fetchall()
    return [dict(row) for row in rows]


def save_weekly_result(season, matchup_period, fantasy_team, opponent,
                       team_score, opponent_score):
    """Archive one completed matchup locally without duplicating reruns."""
    initialize_database()
    team_score = float(team_score)
    opponent_score = float(opponent_score)
    result = "W" if team_score > opponent_score else "L" if team_score < opponent_score else "T"
    saved_at = datetime.now().isoformat(timespec="seconds")
    if _current_scope() is not None:
        period = int(matchup_period)
        _save_scoped("weekly_result", _key(season, period, fantasy_team), {
            "fantasy_season": int(season),
            "matchup_period": period,
            "fantasy_team": str(fantasy_team),
            "opponent": str(opponent),
            "team_score": team_score,
            "opponent_score": opponent_score,
            "result": result,
            "saved_at": saved_at,
        })
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """INSERT INTO weekly_results
               (fantasy_season, matchup_period, fantasy_team, opponent,
                team_score, opponent_score, result, saved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fantasy_season, matchup_period, fantasy_team)
               DO UPDATE SET opponent=excluded.opponent,
                   team_score=excluded.team_score,
                   opponent_score=excluded.opponent_score,
                   result=excluded.result,
                   saved_at=excluded.saved_at""",
            (season, int(matchup_period), fantasy_team, opponent,
             team_score, opponent_score, result, saved_at),
        )


def weekly_result_history(season, fantasy_team):
    """Return archived results newest first for progress displays."""
    initialize_database()
    if _current_scope() is not None:
        records = [item["payload"] for item in _list_scoped("weekly_result")]
        records = [row for row in records if row.get("fantasy_season") == int(season) and row.get("fantasy_team") == str(fantasy_team)]
        records.sort(key=lambda row: row.get("matchup_period", 0), reverse=True)
        return records
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT * FROM weekly_results
               WHERE fantasy_season=? AND fantasy_team=?
               ORDER BY matchup_period DESC""",
            (season, fantasy_team),
        ).fetchall()
    return [dict(row) for row in rows]


def set_app_setting(key, value):
    initialize_database()
    if _current_scope() is not None:
        _save_scoped("app_setting", str(key), {
            "setting_key": str(key), "setting_value": str(value),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """INSERT INTO app_settings (setting_key, setting_value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET
               setting_value=excluded.setting_value, updated_at=excluded.updated_at""",
            (str(key), str(value), datetime.now().isoformat(timespec="seconds")),
        )


def get_app_setting(key, default=None):
    initialize_database()
    if _current_scope() is not None:
        record = _get_scoped("app_setting", str(key))
        return default if record is None else record["payload"].get("setting_value", default)
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key=?", (str(key),)
        ).fetchone()
    return default if row is None else row[0]


def save_intelligence_evidence(evidence_hash, payload, sources, status="complete"):
    initialize_database()
    collected_at = datetime.now().isoformat(timespec="seconds")
    if _current_scope() is not None:
        _save_scoped("intelligence_evidence", str(evidence_hash), {
            "evidence_hash": str(evidence_hash), "collected_at": collected_at,
            "payload": payload, "sources": sources, "status": status,
        })
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """INSERT INTO intelligence_evidence
               (evidence_hash, collected_at, payload_json, sources_json, status)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(evidence_hash) DO UPDATE SET
               collected_at=excluded.collected_at, payload_json=excluded.payload_json,
               sources_json=excluded.sources_json, status=excluded.status""",
            (evidence_hash, collected_at, json.dumps(payload, default=str),
             json.dumps(sources, default=str), status),
        )


def latest_intelligence_evidence():
    initialize_database()
    if _current_scope() is not None:
        rows = _list_scoped("intelligence_evidence", limit=1)
        return None if not rows else rows[0]["payload"]
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM intelligence_evidence ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json"))
    result["sources"] = json.loads(result.pop("sources_json"))
    return result


def save_ai_briefing(evidence_hash, model, briefing):
    initialize_database()
    if _current_scope() is not None:
        _save_scoped("ai_briefing", str(evidence_hash), {
            "evidence_hash": str(evidence_hash), "model": str(model),
            "briefing": briefing,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """INSERT INTO ai_briefings
               (evidence_hash, model, briefing_json, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(evidence_hash) DO UPDATE SET
               model=excluded.model, briefing_json=excluded.briefing_json,
               created_at=excluded.created_at""",
            (evidence_hash, model, json.dumps(briefing, default=str),
             datetime.now().isoformat(timespec="seconds")),
        )


def latest_ai_briefing():
    initialize_database()
    if _current_scope() is not None:
        rows = _list_scoped("ai_briefing", limit=1)
        if not rows:
            return None
        result = dict(rows[0]["payload"])
        evidence = _get_scoped("intelligence_evidence", result["evidence_hash"])
        result["collected_at"] = (
            evidence["payload"].get("collected_at") if evidence else None
        )
        return result
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """SELECT b.*, e.collected_at FROM ai_briefings b
               LEFT JOIN intelligence_evidence e ON e.evidence_hash=b.evidence_hash
               ORDER BY b.created_at DESC LIMIT 1"""
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["briefing"] = json.loads(result.pop("briefing_json"))
    return result


def save_ai_conversation(evidence_hash, question, answer):
    initialize_database()
    if _current_scope() is not None:
        conversation_id = _key(evidence_hash, datetime.now().isoformat(timespec="microseconds"))
        _save_scoped("ai_conversation", conversation_id, {
            "evidence_hash": str(evidence_hash), "question": str(question),
            "answer": str(answer),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """INSERT INTO ai_conversations
               (evidence_hash, question, answer, created_at)
               VALUES (?, ?, ?, ?)""",
            (evidence_hash, question, answer,
             datetime.now().isoformat(timespec="seconds")),
        )


def save_power_snapshot(week, frame):
    initialize_database()
    saved_at = datetime.now().isoformat(timespec="seconds")
    if _current_scope() is not None:
        for _, row in frame.iterrows():
            team_name = str(row["Team"])
            _save_scoped("power_snapshot", _key(week, team_name), {
                "snapshot_week": int(week), "team_name": team_name,
                "rank": int(row["Rank"]), "power_score": row["Power score"],
                "saved_at": saved_at,
            })
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        for _, row in frame.iterrows():
            connection.execute(
                """INSERT INTO power_snapshots
                   (snapshot_week, team_name, rank, power_score, saved_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(snapshot_week, team_name) DO UPDATE SET
                   rank=excluded.rank, power_score=excluded.power_score, saved_at=excluded.saved_at""",
                (int(week), row["Team"], int(row["Rank"]), float(row["Power score"]), saved_at),
            )


def power_snapshot_history():
    initialize_database()
    if _current_scope() is not None:
        records = [item["payload"] for item in _list_scoped("power_snapshot")]
        records.sort(key=lambda row: (row.get("snapshot_week", 0), row.get("rank", 0)))
        return [{key: row.get(key) for key in ("snapshot_week", "team_name", "rank", "power_score")} for row in records]
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT snapshot_week, team_name, rank, power_score FROM power_snapshots ORDER BY snapshot_week, rank"
        ).fetchall()
    return [dict(row) for row in rows]


def save_move_decision(fantasy_team, add_player, drop_player, horizons,
                       season_fppg_change):
    """Save one counterfactual move for later decision and outcome review."""
    initialize_database()
    changes = {
        str(row["Horizon"]): float(row["Projected change"])
        for _, row in horizons.iterrows()
    }
    if _current_scope() is not None:
        decision_id = str(uuid.uuid4())
        _save_scoped("move_decision", decision_id, {
            "id": decision_id,
            "fantasy_team": str(fantasy_team),
            "add_player": str(add_player),
            "drop_player": str(drop_player),
            "one_week_change": changes.get("1 week"),
            "two_week_change": changes.get("2 weeks"),
            "four_week_change": changes.get("4 weeks"),
            "season_fppg_change": season_fppg_change,
            "status": "Pending", "notes": "",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "decided_at": None,
        })
        return decision_id
    with sqlite3.connect(DATABASE_PATH) as connection:
        cursor = connection.execute(
            """INSERT INTO move_decisions
               (fantasy_team, add_player, drop_player, one_week_change,
                two_week_change, four_week_change, season_fppg_change,
                status, saved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?)""",
            (
                fantasy_team, add_player, drop_player,
                changes.get("1 week"), changes.get("2 weeks"),
                changes.get("4 weeks"), season_fppg_change,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cursor.lastrowid


def move_decision_history(fantasy_team, limit=100):
    initialize_database()
    if _current_scope() is not None:
        records = [item["payload"] for item in _list_scoped("move_decision")]
        records = [row for row in records if row.get("fantasy_team") == str(fantasy_team)]
        records.sort(key=lambda row: row.get("saved_at", ""), reverse=True)
        return records[:max(1, int(limit))]
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT * FROM move_decisions WHERE fantasy_team=?
               ORDER BY saved_at DESC LIMIT ?""",
            (fantasy_team, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def update_move_decision(decision_id, fantasy_team, status, notes=""):
    """Record the user's choice without changing anything on ESPN."""
    if status not in {"Pending", "Followed", "Skipped"}:
        raise ValueError("Unknown decision status.")
    initialize_database()
    decided_at = None if status == "Pending" else datetime.now().isoformat(timespec="seconds")
    if _current_scope() is not None:
        key = str(decision_id)
        record = _get_scoped("move_decision", key)
        if record is None:
            return
        payload = dict(record["payload"])
        if payload.get("fantasy_team") != str(fantasy_team):
            return
        payload.update({"status": status, "notes": str(notes), "decided_at": decided_at})
        _save_scoped("move_decision", key, payload)
        return
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """UPDATE move_decisions SET status=?, notes=?, decided_at=?
               WHERE id=? AND fantasy_team=?""",
            (status, notes, decided_at, int(decision_id), fantasy_team),
        )
