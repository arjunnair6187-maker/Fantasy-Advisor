"""Background evidence collector that runs while the Streamlit process is open."""

from __future__ import annotations

from datetime import datetime
import threading
import time
import pandas as pd
from account_store import get_provider_credentials
from advice_engine import build_player_rows, injury_pool_from_league, rank_waivers
from ai_intelligence import (AI_DATA_SHARING_SETTING, ai_is_configured,
    configured_model, evidence_hash, generate_briefing)
from database import (get_app_setting, latest_ai_briefing, save_ai_briefing,
    save_intelligence_evidence, tenant_scope)
from espn_data import ESPN_SEASON_YEAR, connect_to_league
from nba_schedule import get_matchup_week_schedule
from news_data import fetch_nba_news, filter_relevant_news
from week_state import effective_matchup_period


_workers: dict[tuple[str, str], dict] = {}
_state_lock = threading.Lock()


def _matchup_for_team(league, team):
    period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    try:
        matchups = league.box_scores(matchup_period=period)
    except Exception:
        try:
            matchups = league.scoreboard(matchupPeriod=period)
        except TypeError:
            matchups = league.scoreboard()
    return next((matchup for matchup in matchups if team.team_id in {
        matchup.home_team.team_id, matchup.away_team.team_id
    }), None)


def _score(matchup, side):
    for name in [f"{side}_score", f"{side}_team_live_score", f"{side}_final_score"]:
        value = getattr(matchup, name, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return 0.0


def _player_evidence(rows):
    return [{
        "player": row.get("Player"), "nba_team": row.get("NBA team"),
        "positions": row.get("Positions"),
        "injury_status": row.get("Injury status"),
        "projection_fppg": row.get("Projected FP/G"),
        "advice_fppg": row.get("Advice score"),
        "fp_last_7": row.get("FP last 7"),
        "fp_last_14": row.get("FP last 14"),
        "fp_last_30": row.get("FP last 30"),
        "completed_games": row.get("Season games"),
    } for row in rows]


def collect_once(
    user_id, league_id, connection_id, provider_league_id, selected_name,
    season=ESPN_SEASON_YEAR,
):
    """Collect verified data, persist it, and interpret only changed evidence."""
    with tenant_scope(user_id, league_id):
        credentials = get_provider_credentials(user_id, connection_id)
        league = connect_to_league(
            year=season, credentials=credentials, league_id=provider_league_id
        )
        team = next((candidate for candidate in league.teams if candidate.team_name == selected_name), None)
        if team is None:
            raise RuntimeError("SelectedTeamNotFound")
                    data_gaps = []
        try:
            previous_league = connect_to_league(
                year=season - 1, credentials=credentials, league_id=provider_league_id
            )
        except Exception:
            previous_league = None
                
        try:
            schedule = get_matchup_week_schedule()
        except Exception as error:
            # Continue evidence collection if the NBA schedule is unavailable.
            schedule = {
                "status": "unavailable",
                "week_name": None,
                "start_date": None,
                "end_date": None,
                "game_counts": pd.DataFrame(columns=["NBA team", "Games"]),
            }
            data_gaps.append(
                f"NBA schedule unavailable ({type(error).__name__})."
            )
        league.currentMatchupPeriod = effective_matchup_period(league, schedule)
        my_rows = build_player_rows(
            league, team, set(), previous_league=previous_league
        )
        matchup = _matchup_for_team(league, team)
        opponent_rows = []
        matchup_evidence = {"opponent": None, "my_score": 0.0, "opponent_score": 0.0}
        if matchup is not None:
            is_home = matchup.home_team.team_id == team.team_id
            opponent = matchup.away_team if is_home else matchup.home_team
            opponent_rows = build_player_rows(
                league, opponent, set(), previous_league=previous_league
            )
            matchup_evidence = {
                "opponent": opponent.team_name,
                "my_score": _score(matchup, "home" if is_home else "away"),
                "opponent_score": _score(matchup, "away" if is_home else "home"),
            }
        waivers = rank_waivers(
            league, schedule["game_counts"], size=30,
            previous_league=previous_league,
            injury_pool=injury_pool_from_league(league),
        )
        waiver_records = [] if waivers.empty else waivers.head(15).where(
            waivers.head(15).notna(), None
        ).to_dict("records")
        relevant_names = [row["Player"] for row in my_rows + opponent_rows]
        relevant_names.extend(row.get("Player") for row in waiver_records if row.get("Player"))
        
        try:
            news_items, news_time = fetch_nba_news()
            relevant_news = filter_relevant_news(news_items, relevant_names)
            news_records = [{
                "title": item.get("title"), "published": item.get("published"),
                "players": item.get("players"), "impact": item.get("impact"),
                "injury_related": item.get("injury_related"),
            } for item in relevant_news[:20]]
            news_timestamp = news_time.isoformat()
        except Exception as error:
            news_records, news_timestamp = [], None
            data_gaps.append(f"News feed unavailable ({type(error).__name__}).")
        if previous_league is None:
            data_gaps.append("Last-season ESPN context was unavailable.")
        collected_at = datetime.now().isoformat(timespec="seconds")
        payload = {
            "collected_at": collected_at,
            "fantasy_team": team.team_name,
            "fantasy_period": int(getattr(league, "currentMatchupPeriod", 1) or 1),
            "matchup": matchup_evidence,
            "schedule": {
                "week": schedule.get("week_name"),
                "start": str(schedule.get("start_date")),
                "end": str(schedule.get("end_date")),
                "team_game_counts": schedule["game_counts"].to_dict("records"),
            },
            "my_roster": _player_evidence(my_rows),
            "opponent_roster": _player_evidence(opponent_rows),
            "top_waivers": waiver_records,
            "relevant_news": news_records,
            "data_gaps": data_gaps,
        }
        sources = [
            {"source": "ESPN private league", "fetched_at": collected_at,
             "covers": "rosters, matchup, injuries, projections and game performance"},
            {"source": "NBA schedule", "fetched_at": collected_at,
             "covers": "dated games and weekly volume"},
            {"source": "NBA RSS news", "fetched_at": news_timestamp,
             "covers": "matched headlines and injury context"},
        ]
        fingerprint = evidence_hash(payload)
        save_intelligence_evidence(fingerprint, payload, sources)
        latest = latest_ai_briefing()
        allow_external_processing = (
            get_app_setting(AI_DATA_SHARING_SETTING, "false") == "true"
        )
        desired_model = (
            configured_model()
            if ai_is_configured() and allow_external_processing
            else "deterministic"
        )
        if (
            latest is None or latest["evidence_hash"] != fingerprint
            or latest.get("model") != desired_model
        ):
            briefing, model, _ = generate_briefing(payload)
            save_ai_briefing(fingerprint, model, briefing)
        return fingerprint


def _loop(key, interval_seconds):
    while True:
        with _state_lock:
            worker = _workers.get(key)
            if worker is None or worker["stop"].is_set():
                break
            target = dict(worker["target"])
            state = worker["state"]
            state["running"] = True
            state["last_started"] = datetime.now().isoformat(timespec="seconds")
            state["last_error"] = None
        try:
            fingerprint = collect_once(**target)
            with _state_lock:
                state["last_hash"] = fingerprint
                state["last_completed"] = datetime.now().isoformat(timespec="seconds")
        except Exception as error:
            with _state_lock:
                state["last_error"] = type(error).__name__
        finally:
            with _state_lock:
                state["running"] = False
        with _state_lock:
            worker = _workers.get(key)
            if worker is None or worker["stop"].is_set():
                break
            wake = worker["wake"]
        wake.wait(interval_seconds)
        wake.clear()
    with _state_lock:
        worker = _workers.get(key)
        if worker is not None and worker["thread"] is threading.current_thread():
            _workers.pop(key, None)


def start_background_worker(
    user_id, league_id, connection_id, provider_league_id, selected_team,
    season=ESPN_SEASON_YEAR, interval_seconds=150,
):
    """Start or refresh one worker for this owner's league only."""
    key = (str(user_id), str(league_id))
    target = {
        "user_id": str(user_id), "league_id": str(league_id),
        "connection_id": str(connection_id),
        "provider_league_id": str(provider_league_id),
        "selected_name": str(selected_team), "season": int(season),
    }
    with _state_lock:
        worker = _workers.get(key)
        if worker is not None and worker["thread"].is_alive():
            changed = worker["target"] != target
            worker["target"] = target
            if changed:
                worker["wake"].set()
            return
        stop = threading.Event()
        wake = threading.Event()
        state = {
            "running": False, "last_started": None, "last_completed": None,
            "last_error": None, "last_hash": None,
        }
        worker = {
            "stop": stop, "wake": wake, "state": state,
            "target": target, "thread": None,
        }
        thread = threading.Thread(
            target=_loop,
            args=(key, max(60, int(interval_seconds))),
            daemon=True,
            name=f"fantasy-intelligence-{key[1][:8]}",
        )
        worker["thread"] = thread
        _workers[key] = worker
        thread.start()


def request_background_refresh(user_id, league_id):
    key = (str(user_id), str(league_id))
    with _state_lock:
        worker = _workers.get(key)
        if worker is not None:
            worker["wake"].set()


def stop_background_worker(user_id, league_id):
    key = (str(user_id), str(league_id))
    with _state_lock:
        worker = _workers.get(key)
        if worker is not None:
            worker["stop"].set()
            worker["wake"].set()


def stop_user_workers(user_id):
    owner_id = str(user_id)
    with _state_lock:
        for (worker_owner, _league_id), worker in list(_workers.items()):
            if worker_owner == owner_id:
                worker["stop"].set()
                worker["wake"].set()


def worker_status(user_id, league_id):
    key = (str(user_id), str(league_id))
    with _state_lock:
        worker = _workers.get(key)
        if worker is None:
            return {
                "running": False, "last_started": None, "last_completed": None,
                "last_error": None, "last_hash": None,
            }
        return dict(worker["state"])
