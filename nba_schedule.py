"""Fetch and summarize the official NBA schedule with a local cache."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import time

import pandas as pd
from nba_api.stats.endpoints.scheduleleaguev2 import ScheduleLeagueV2
import requests


NBA_SEASON = "2026-27"
CACHE_PATH = Path(__file__).with_name("nba_schedule_cache.json")
NBA_CDN_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"


def _load_cached_frames():
    if not CACHE_PATH.exists():
        return None
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    saved_at = datetime.fromisoformat(payload["saved_at"])
    if datetime.now() - saved_at > timedelta(days=7):
        return None
    return pd.DataFrame(payload["schedule"]), pd.DataFrame(payload["weeks"])


def _save_cached_frames(schedule, weeks):
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "schedule": schedule.where(pd.notna(schedule), None).to_dict(orient="records"),
        "weeks": weeks.where(pd.notna(weeks), None).to_dict(orient="records"),
    }
    CACHE_PATH.write_text(json.dumps(payload, default=str), encoding="utf-8")


def _fetch_schedule_frames():
    """Retry NBA.com, then safely fall back to a recent local copy."""
    last_error = None
    try:
        frames = ScheduleLeagueV2(season=NBA_SEASON, timeout=20).get_data_frames()
        schedule, weeks = frames[0].copy(), frames[1].copy()
        _save_cached_frames(schedule, weeks)
        return schedule, weeks, "live"
    except Exception as error:
        last_error = error
        time.sleep(1)
    try:
        response = requests.get(
            NBA_CDN_URL,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/"},
            timeout=20,
        )
        response.raise_for_status()
        root = response.json().get("leagueSchedule", {})
        game_rows = []
        for game_date in root.get("gameDates", []):
            for game in game_date.get("games", []):
                game_rows.append({
                    "gameDateEst": game.get("gameDateTimeEst") or game_date.get("gameDate"),
                    "gameLabel": game.get("gameLabel", ""),
                    "homeTeam_teamTricode": game.get("homeTeam", {}).get("teamTricode"),
                    "awayTeam_teamTricode": game.get("awayTeam", {}).get("teamTricode"),
                })
        week_rows = root.get("weeks") or root.get("seasonWeeks") or []
        schedule, weeks = pd.DataFrame(game_rows), pd.DataFrame(week_rows)
        required = {"weekNumber", "weekName", "startDate", "endDate"}
        if schedule.empty or weeks.empty or not required.issubset(weeks.columns):
            raise ValueError("NBA CDN schedule format was incomplete.")
        _save_cached_frames(schedule, weeks)
        return schedule, weeks, "NBA CDN fallback"
    except Exception as error:
        last_error = error
    cached = _load_cached_frames()
    if cached is not None:
        return cached[0], cached[1], "cached"
    raise RuntimeError("NBA schedule sources timed out and no saved schedule is available.") from last_error


def get_matchup_week_schedule(reference_date=None):
    """
    Return the current NBA week, or the next week if the season has not begun.
    Preseason games are excluded.
    """

    if reference_date is None:
        reference_date = date.today()

    schedule, weeks, source = _fetch_schedule_frames()

    schedule["game_date"] = pd.to_datetime(
        schedule["gameDateEst"],
        errors="coerce",
    ).dt.date

    weeks["start_date"] = pd.to_datetime(
        weeks["startDate"],
        errors="coerce",
    ).dt.date
    weeks["end_date"] = pd.to_datetime(
        weeks["endDate"],
        errors="coerce",
    ).dt.date

    matching_weeks = weeks[
        (weeks["start_date"] <= reference_date)
        & (weeks["end_date"] >= reference_date)
    ]

    period_status = "current"

    if matching_weeks.empty:
        matching_weeks = weeks[
            weeks["start_date"] > reference_date
        ].sort_values("start_date").head(1)
        period_status = "upcoming"

    if matching_weeks.empty:
        raise ValueError(
            "No current or upcoming NBA schedule week was found."
        )

    selected_week = matching_weeks.iloc[0]
    start_date = selected_week["start_date"]
    end_date = selected_week["end_date"]

    week_games = schedule[
        (schedule["game_date"] >= start_date)
        & (schedule["game_date"] <= end_date)
        & (schedule["gameLabel"].fillna("") != "Preseason")
    ].copy()

    home_teams = week_games[
        ["homeTeam_teamTricode"]
    ].rename(columns={"homeTeam_teamTricode": "NBA team"})

    away_teams = week_games[
        ["awayTeam_teamTricode"]
    ].rename(columns={"awayTeam_teamTricode": "NBA team"})

    team_games = pd.concat(
        [home_teams, away_teams],
        ignore_index=True,
    )

    game_counts = (
        team_games.groupby("NBA team")
        .size()
        .reset_index(name="Games")
        .sort_values(
            ["Games", "NBA team"],
            ascending=[False, True],
        )
        .reset_index(drop=True)
    )

    return {
        "status": period_status,
        "week_name": selected_week["weekName"],
        "week_number": int(selected_week["weekNumber"]),
        "start_date": start_date,
        "end_date": end_date,
        "games": week_games,
        "game_counts": game_counts,
        "source": source,
    }


def get_upcoming_week_schedules(reference_date=None, count=4):
    """Return current/upcoming NBA calendar weeks without repeating downloads."""
    if reference_date is None:
        reference_date = date.today()
    schedule, weeks, source = _fetch_schedule_frames()
    schedule["game_date"] = pd.to_datetime(schedule["gameDateEst"], errors="coerce").dt.date
    weeks["start_date"] = pd.to_datetime(weeks["startDate"], errors="coerce").dt.date
    weeks["end_date"] = pd.to_datetime(weeks["endDate"], errors="coerce").dt.date
    selected = weeks[weeks["end_date"] >= reference_date].sort_values("start_date").head(count)
    results = []
    for _, week in selected.iterrows():
        week_games = schedule[
            (schedule["game_date"] >= week["start_date"])
            & (schedule["game_date"] <= week["end_date"])
            & (schedule["gameLabel"].fillna("") != "Preseason")
        ].copy()
        home = week_games[["homeTeam_teamTricode"]].rename(columns={"homeTeam_teamTricode": "NBA team"})
        away = week_games[["awayTeam_teamTricode"]].rename(columns={"awayTeam_teamTricode": "NBA team"})
        counts = (
            pd.concat([home, away], ignore_index=True).groupby("NBA team").size()
            .reset_index(name="Games").sort_values(["Games", "NBA team"], ascending=[False, True])
            .reset_index(drop=True)
        )
        results.append({
            "status": "current" if week["start_date"] <= reference_date <= week["end_date"] else "upcoming",
            "week_name": week["weekName"], "week_number": int(week["weekNumber"]),
            "start_date": week["start_date"], "end_date": week["end_date"],
            "games": week_games, "game_counts": counts, "source": source,
        })
    return results


def get_completed_week_schedules(reference_date=None, count=30):
    """Return completed NBA calendar weeks, oldest to newest."""
    if reference_date is None:
        reference_date = date.today()
    schedule, weeks, source = _fetch_schedule_frames()
    schedule["game_date"] = pd.to_datetime(schedule["gameDateEst"], errors="coerce").dt.date
    weeks["start_date"] = pd.to_datetime(weeks["startDate"], errors="coerce").dt.date
    weeks["end_date"] = pd.to_datetime(weeks["endDate"], errors="coerce").dt.date
    selected = weeks[weeks["end_date"] < reference_date].sort_values("start_date").tail(count)
    results = []
    for _, week in selected.iterrows():
        week_games = schedule[
            (schedule["game_date"] >= week["start_date"])
            & (schedule["game_date"] <= week["end_date"])
            & (schedule["gameLabel"].fillna("") != "Preseason")
        ].copy()
        home = week_games[["homeTeam_teamTricode"]].rename(columns={"homeTeam_teamTricode": "NBA team"})
        away = week_games[["awayTeam_teamTricode"]].rename(columns={"awayTeam_teamTricode": "NBA team"})
        counts = (
            pd.concat([home, away], ignore_index=True).groupby("NBA team").size()
            .reset_index(name="Games").sort_values(["Games", "NBA team"], ascending=[False, True])
            .reset_index(drop=True)
        )
        results.append({
            "status": "completed", "week_name": week["weekName"],
            "week_number": int(week["weekNumber"]),
            "start_date": week["start_date"], "end_date": week["end_date"],
            "games": week_games, "game_counts": counts, "source": source,
        })
    return results


def get_team_defense_context(reference_date=None):
    """Estimate opponent difficulty from current-season NBA points allowed."""
    if reference_date is None:
        reference_date = date.today()
    schedule, _, _ = _fetch_schedule_frames()
    schedule["game_date"] = pd.to_datetime(schedule["gameDateEst"], errors="coerce").dt.date
    required = {"homeTeam_score", "awayTeam_score", "homeTeam_teamTricode", "awayTeam_teamTricode"}
    if not required.issubset(schedule.columns):
        return {}
    completed = schedule[schedule["game_date"] < reference_date]
    allowed = {}
    for _, game in completed.iterrows():
        try:
            home_score, away_score = float(game["homeTeam_score"]), float(game["awayTeam_score"])
        except (TypeError, ValueError):
            continue
        if home_score <= 0 or away_score <= 0:
            continue
        allowed.setdefault(game["homeTeam_teamTricode"], []).append(away_score)
        allowed.setdefault(game["awayTeam_teamTricode"], []).append(home_score)
    return {team: sum(values) / len(values) for team, values in allowed.items() if values}


def teams_playing_on(schedule_result, target_date=None):
    """Return NBA tricodes with a non-preseason game on one date."""
    if target_date is None:
        target_date = date.today()
    games = schedule_result["games"]
    today = games[games["game_date"] == target_date]
    return set(today["homeTeam_teamTricode"]) | set(today["awayTeam_teamTricode"])
