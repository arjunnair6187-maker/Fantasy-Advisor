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
NBA_CDN_URLS = (
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
)
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_SCHEDULE_CHUNK_DAYS = 45
ESPN_SCHEDULE_TIMEOUT_SECONDS = 10
_FETCH_RETRY_AFTER = 0.0
_LAST_FETCH_ERROR = None
_LAST_FETCH_DIAGNOSTIC = ""


def _schedule_error_detail(source, error):
    """Return provider/status diagnostics without response bodies or secrets."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        return f"{source}: HTTP {status}"
    if isinstance(error, requests.Timeout):
        return f"{source}: timeout"
    if isinstance(error, ValueError):
        return f"{source}: invalid or empty schedule response"
    if isinstance(error, requests.RequestException):
        return f"{source}: {type(error).__name__}"
    return f"{source}: {type(error).__name__}"


def _load_cached_frames():
    try:
        if not CACHE_PATH.exists():
            return None
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        saved_at = datetime.fromisoformat(payload["saved_at"])
        if datetime.now() - saved_at > timedelta(days=7):
            return None
        schedule, weeks = pd.DataFrame(payload["schedule"]), pd.DataFrame(payload["weeks"])
        if schedule.empty or weeks.empty:
            return None
        return schedule, weeks
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_cached_frames(schedule, weeks):
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "schedule": schedule.where(pd.notna(schedule), None).to_dict(orient="records"),
        "weeks": weeks.where(pd.notna(weeks), None).to_dict(orient="records"),
    }
    try:
        CACHE_PATH.write_text(json.dumps(payload, default=str), encoding="utf-8")
    except OSError:
        # Streamlit Cloud may mount the source tree read-only. The decorated
        # app loaders still keep a process-local copy after a successful fetch.
        pass


def _season_date_range():
    """Return a broad date range covering this season and its playoffs."""
    season_start_year = int(NBA_SEASON.split("-", maxsplit=1)[0])
    return date(season_start_year, 10, 1), date(season_start_year + 1, 7, 1)


def _date_chunks(start_date, end_date, chunk_days=ESPN_SCHEDULE_CHUNK_DAYS):
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def _espn_event_to_schedule_row(event):
    """Convert one ESPN scoreboard event into the columns used by the app."""
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    home = next((item for item in competitors if item.get("homeAway") == "home"), None)
    away = next((item for item in competitors if item.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    # ESPN timestamps are UTC. NBA schedule dates are conventionally grouped
    # by the Eastern calendar day; using the date portion as-is shifts many
    # evening games into the following day.
    raw_date = competition.get("date") or event.get("date")
    parsed_date = pd.to_datetime(raw_date, errors="coerce", utc=True)
    if pd.isna(parsed_date):
        return None
    game_date = parsed_date.tz_convert("America/New_York").date()

    event_season = event.get("season") or {}
    season_type = event_season.get("type")
    try:
        season_type = int(season_type)
    except (TypeError, ValueError):
        season_type = None
    # ESPN season type 1 is preseason. Exclude it from fantasy planning.
    if season_type == 1:
        return None

    def team_code(competitor):
        team = competitor.get("team") or {}
        code = team.get("abbreviation") or team.get("shortDisplayName")
        return {
            "GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "WSH": "WAS",
        }.get(code, code)

    def score(competitor):
        value = competitor.get("score")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "gameId": event.get("id") or f"{game_date.isoformat()}:{team_code(home)}:{team_code(away)}",
        "gameDateEst": game_date.isoformat(),
        "gameLabel": {1: "Preseason", 3: "Playoffs"}.get(season_type, "Regular Season"),
        "homeTeam_teamTricode": team_code(home),
        "awayTeam_teamTricode": team_code(away),
        "homeTeam_score": score(home),
        "awayTeam_score": score(away),
    }


def _frames_from_espn_events(events):
    rows = []
    for event in events:
        row = _espn_event_to_schedule_row(event)
        if row and row["homeTeam_teamTricode"] and row["awayTeam_teamTricode"]:
            rows.append(row)
    schedule = pd.DataFrame(rows)
    if schedule.empty:
        raise ValueError("ESPN returned no usable NBA schedule events.")
    if "gameId" in schedule.columns:
        schedule = schedule.drop_duplicates(subset=["gameId"], keep="last")
    schedule["game_date"] = pd.to_datetime(schedule["gameDateEst"], errors="coerce").dt.date
    schedule = schedule.dropna(subset=["game_date"])
    first_game, last_game = schedule["game_date"].min(), schedule["game_date"].max()
    first_monday = first_game - timedelta(days=first_game.weekday())
    last_sunday = last_game + timedelta(days=6 - last_game.weekday())
    week_rows = []
    week_start = first_monday
    week_number = 1
    while week_start <= last_sunday:
        week_end = week_start + timedelta(days=6)
        week_rows.append({
            "weekNumber": week_number,
            "weekName": f"{week_start:%b %d} – {week_end:%b %d}",
            "startDate": week_start.isoformat(),
            "endDate": week_end.isoformat(),
        })
        week_start += timedelta(days=7)
        week_number += 1
    return schedule.drop(columns=["game_date"]), pd.DataFrame(week_rows)


def _fetch_espn_schedule_frames():
    """Fetch this NBA season in date chunks from ESPN's public scoreboard."""
    start_date, end_date = _season_date_range()
    events_by_id = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FantasyAdvisor/1.0)",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.espn.com/nba/",
    }
    for chunk_start, chunk_end in _date_chunks(start_date, end_date):
        response = requests.get(
            ESPN_SCOREBOARD_URL,
            params={
                "dates": f"{chunk_start:%Y%m%d}-{chunk_end:%Y%m%d}",
                "limit": 500,
            },
            headers=headers,
            timeout=ESPN_SCHEDULE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("ESPN NBA scoreboard response had no events list.")
        for event in events:
            event_id = event.get("id")
            if event_id:
                events_by_id[str(event_id)] = event
            else:
                events_by_id[f"{event.get('date')}:{len(events_by_id)}"] = event

    schedule, weeks = _frames_from_espn_events(list(events_by_id.values()))
    return schedule, weeks


def _fetch_schedule_frames():
    """Use ESPN's schedule feed first, with NBA sources and cache as backups."""
    global _FETCH_RETRY_AFTER, _LAST_FETCH_ERROR, _LAST_FETCH_DIAGNOSTIC
    if time.monotonic() < _FETCH_RETRY_AFTER:
        message = _LAST_FETCH_DIAGNOSTIC or "NBA schedule sources are temporarily unavailable."
        raise RuntimeError(f"{message} Retrying after a short pause.") from _LAST_FETCH_ERROR
    last_error = None
    source_errors = []

    # ESPN is the primary source because Streamlit Cloud receives HTTP 403
    # responses from the NBA CDN. Fetch the current season in bounded date
    # chunks and normalize it to the same schema as the NBA schedule feeds.
    try:
        schedule, weeks = _fetch_espn_schedule_frames()
        _save_cached_frames(schedule, weeks)
        _FETCH_RETRY_AFTER, _LAST_FETCH_ERROR, _LAST_FETCH_DIAGNOSTIC = 0.0, None, ""
        return schedule, weeks, "ESPN primary schedule"
    except Exception as error:
        last_error = error
        source_errors.append(_schedule_error_detail("ESPN scoreboard", error))

    try:
        frames = ScheduleLeagueV2(season=NBA_SEASON, timeout=20).get_data_frames()
        if len(frames) < 2 or frames[0].empty or frames[1].empty:
            raise ValueError("NBA Stats returned an empty schedule.")
        schedule, weeks = frames[0].copy(), frames[1].copy()
        required = {"gameDateEst", "homeTeam_teamTricode", "awayTeam_teamTricode"}
        week_required = {"weekNumber", "weekName", "startDate", "endDate"}
        if not required.issubset(schedule.columns) or not week_required.issubset(weeks.columns):
            raise ValueError("NBA Stats schedule response was incomplete.")
        _save_cached_frames(schedule, weeks)
        _FETCH_RETRY_AFTER, _LAST_FETCH_ERROR, _LAST_FETCH_DIAGNOSTIC = 0.0, None, ""
        return schedule, weeks, "NBA Stats fallback"
    except Exception as error:
        last_error = error
        source_errors.append(_schedule_error_detail("NBA Stats", error))
        time.sleep(1)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Accept": "application/json,text/plain,*/*",
    }
    for index, cdn_url in enumerate(NBA_CDN_URLS, start=1):
        try:
            response = requests.get(cdn_url, headers=headers, timeout=12)
            response.raise_for_status()
            root = response.json().get("leagueSchedule", {})
            game_rows = []
            for game_date in root.get("gameDates", []):
                for game in game_date.get("games", []):
                    game_rows.append({
                        "gameDateEst": game.get("gameDateEst") or game_date.get("gameDate") or game.get("gameDateTimeEst"),
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
            _FETCH_RETRY_AFTER, _LAST_FETCH_ERROR, _LAST_FETCH_DIAGNOSTIC = 0.0, None, ""
            return schedule, weeks, "NBA CDN fallback"
        except Exception as error:
            last_error = error
            source_errors.append(_schedule_error_detail(f"NBA CDN source {index}", error))
    cached = _load_cached_frames()
    if cached is not None:
        _FETCH_RETRY_AFTER, _LAST_FETCH_ERROR, _LAST_FETCH_DIAGNOSTIC = 0.0, None, ""
        return cached[0], cached[1], "cached"
    _LAST_FETCH_DIAGNOSTIC = "; ".join(source_errors) or "No schedule source returned data."
    _LAST_FETCH_ERROR = last_error
    _FETCH_RETRY_AFTER = time.monotonic() + 300
    raise RuntimeError(
        f"NBA schedule sources failed ({_LAST_FETCH_DIAGNOSTIC}); no saved schedule is available."
    ) from last_error


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
