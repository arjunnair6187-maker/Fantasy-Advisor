"""Deterministic, explainable fantasy-basketball advice."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pandas as pd

from player_metrics import blended_projection, custom_fppg_from_espn_player, rolling_custom_fppg, rolling_stat_average
from projections import normalize_nba_team


STARTER_SLOTS = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "UTIL", "UTIL"]
INACTIVE_STATUSES = {
    "OUT", "O", "IR", "INJURY RESERVE", "INJURED RESERVE",
    "SUSPENSION", "SUSPENDED",
}
HEALTHY_STATUSES = {"ACTIVE", "NORMAL", "HEALTHY", ""}
BASE_POSITIONS = ["PG", "SG", "SF", "PF", "C"]


def player_positions(player) -> list[str]:
    """Return only real basketball positions, including secondary positions."""
    eligible = getattr(player, "eligibleSlots", None) or []
    raw = [getattr(player, "position", ""), *eligible]
    found = []
    for value in raw:
        for part in str(value).upper().replace("-", "/").split("/"):
            part = part.strip()
            if part in BASE_POSITIONS and part not in found:
                found.append(part)
    return sorted(found, key=BASE_POSITIONS.index)


def _score_for_advice(detail, reference_date=None):
    reference_date = reference_date or date.today()
    # A dated ESPN stat row can contain an in-progress game. Only games from
    # before today are safe to treat as completed performance.
    completed_through = reference_date - timedelta(days=1)
    fp7, games7 = rolling_custom_fppg(detail, 7, completed_through)
    fp14, games14 = rolling_custom_fppg(detail, 14, completed_through)
    fp30, games30 = rolling_custom_fppg(detail, 30, completed_through)
    season, season_games = rolling_custom_fppg(detail, 370, completed_through)
    score = fp14 if fp14 is not None else fp30 if fp30 is not None else season
    return score, fp7, fp14, fp30, season_games, (games7, games14, games30)


def build_player_rows(league, team, teams_playing_today: set[str], reference_date=None,
                      previous_league=None, details_override=None,
                      previous_details_override=None):
    """Build grounded daily inputs for one fantasy roster."""
    reference_date = reference_date or date.today()
    roster = list(getattr(team, "roster", []))
    details = details_override or {}
    if roster and details_override is None:
        try:
            result = league.player_info(playerId=[p.playerId for p in roster])
            if not isinstance(result, list):
                result = [result]
            details = {p.playerId: p for p in result if p is not None}
        except Exception:
            details = {}

    rows = []
    previous_details = previous_details_override or {}
    if previous_league is not None and roster and previous_details_override is None:
        try:
            previous = previous_league.player_info(playerId=[p.playerId for p in roster])
            if not isinstance(previous, list):
                previous = [previous]
            previous_details = {p.playerId: p for p in previous if p is not None}
        except Exception:
            previous_details = {}
    for player in roster:
        detail = details.get(player.playerId, player)
        score, fp7, fp14, fp30, season_games, window_games = _score_for_advice(
            detail, reference_date
        )
        projection = blended_projection(detail, previous_player=previous_details.get(player.playerId))
        projected = projection["blended_fppg"]
        completed_sample = window_games[1] or window_games[2] or season_games
        if score is None:
            score = projected
        elif projected is not None:
            # One early game receives 10% weight; recent form earns up to 75%
            # after a useful sample instead of immediately replacing projection.
            recent_weight = min(0.75, completed_sample / 10)
            score = round(recent_weight * score + (1 - recent_weight) * projected, 2)
        nba_team = normalize_nba_team(getattr(player, "proTeam", ""))
        status = str(getattr(player, "injuryStatus", "Unknown") or "Unknown")
        rows.append(
            {
                "Player": player.name,
                "NBA team": nba_team or "Unknown",
                "Positions": "/".join(player_positions(player)) or "Unknown",
                "Eligible": player_positions(player),
                "Injury status": status,
                "Game today": nba_team in teams_playing_today,
                "FP last 7": fp7,
                "FP last 14": fp14,
                "FP last 30": fp30,
                "Advice score": score,
                "Projected FP/G": projection["blended_fppg"],
                "Projection basis": projection["projection_basis"],
                "Season games": season_games,
                "Window games": window_games,
            }
        )
    return rows


def _eligible_for_slot(row, slot):
    positions = set(row["Eligible"])
    if slot == "UTIL":
        return bool(positions & {"PG", "SG", "SF", "PF", "C", "G", "F"})
    if slot == "G":
        return bool(positions & {"PG", "SG", "G"})
    if slot == "F":
        return bool(positions & {"SF", "PF", "F"})
    return slot in positions


def recommend_lineup(rows):
    """Assign today's available players to legal slots using recent custom FP/G."""
    candidates = [
        row for row in rows
        if row["Game today"] and row["Injury status"].upper() not in INACTIVE_STATUSES
    ]
    candidates.sort(key=lambda row: row["Advice score"] if row["Advice score"] is not None else -1, reverse=True)
    # Exact small-roster optimizer: choose the highest-scoring legal assignment.
    states = {0: (0.0, [])}
    for row in candidates:
        next_states = dict(states)
        value = float(row["Advice score"] or 0)
        for mask, (total, assignments) in states.items():
            for index, slot in enumerate(STARTER_SLOTS):
                bit = 1 << index
                if not mask & bit and _eligible_for_slot(row, slot):
                    candidate = (total + value, assignments + [(slot, row["Player"])])
                    if candidate[0] > next_states.get(mask | bit, (-1, []))[0]:
                        next_states[mask | bit] = candidate
        states = next_states
    assignments = max(states.values(), key=lambda item: (len(item[1]), item[0]))[1]

    slot_by_player = {player: slot for slot, player in assignments}
    output = []
    for row in rows:
        status = row["Injury status"].upper()
        if not row["Game today"]:
            recommendation = "Bench"
            reason = "No NBA game today."
        elif status in INACTIVE_STATUSES:
            recommendation = "Bench / IR"
            reason = f"Listed {row['Injury status']}; do not start unless the status changes."
        elif row["Player"] in slot_by_player:
            recommendation = f"Start — {slot_by_player[row['Player']]}"
            if row["Advice score"] is None:
                reason = "Has a game and fits this slot, but recent custom scoring data is unavailable."
            elif row["FP last 14"] is None and row["FP last 30"] is None:
                reason = f"Best legal slot fit using the available projection ({row['Advice score']:.1f} FP/G)."
            else:
                reason = f"Best legal slot fit among today's players ({row['Advice score']:.1f} recent custom FP/G)."
        else:
            recommendation = "Bench"
            reason = "Has a game, but higher-rated eligible players fill the available slots."
        enriched = dict(row)
        possible_change = (
            "Recheck injury status before tipoff."
            if status not in HEALTHY_STATUSES
            else "May change after injuries, news, or new game results."
        )
        enriched.update({"Recommendation": recommendation, "Reason": reason, "May update if": possible_change})
        output.append(enriched)
    return output


def rank_waivers(league, game_counts, size=50, previous_league=None, injury_pool=None):
    """Rank free agents with recent form weighted above season form."""
    players = list(league.free_agents(size=size))
    details = {}
    if players:
        try:
            result = league.player_info(playerId=[p.playerId for p in players])
            if not isinstance(result, list):
                result = [result]
            details = {p.playerId: p for p in result if p is not None}
        except Exception:
            details = {}
    games_map = dict(zip(game_counts["NBA team"], game_counts["Games"]))
    rows = []
    opportunity_pool = list(injury_pool or []) + players
    previous_details = {}
    if previous_league is not None and players:
        try:
            previous = previous_league.player_info(playerId=[p.playerId for p in players])
            if not isinstance(previous, list):
                previous = [previous]
            previous_details = {p.playerId: p for p in previous if p is not None}
        except Exception:
            previous_details = {}
    for player in players:
        detail = details.get(player.playerId, player)
        completed_through = date.today() - timedelta(days=1)
        season, season_games = rolling_custom_fppg(detail, 370, completed_through)
        projection = blended_projection(detail, previous_player=previous_details.get(player.playerId))
        fp14, games14 = rolling_custom_fppg(detail, 14, completed_through)
        minutes7 = rolling_stat_average(detail, "MIN", 7, completed_through)
        minutes14 = rolling_stat_average(detail, "MIN", 14, completed_through)
        nba_team = normalize_nba_team(getattr(player, "proTeam", ""))
        baseline = season if season is not None else projection["blended_fppg"]
        if fp14 is not None and baseline is not None:
            recent_weight = min(0.65, games14 / 10)
            weighted = round(recent_weight * fp14 + (1 - recent_weight) * baseline, 2)
        else:
            weighted = fp14 if fp14 is not None else baseline
        rows.append({
            "Player": player.name,
            "NBA team": nba_team or "Unknown",
            "Positions": "/".join(player_positions(player)) or "Unknown",
            "Injury status": str(getattr(player, "injuryStatus", "Unknown")),
            "FP/G last 14": fp14,
            "14-day games": games14,
            "Season FP/G": season,
            "Projected FP/G": projection["blended_fppg"],
            "Projection basis": projection["projection_basis"],
            "Season games": season_games,
            "Minutes last 7": minutes7,
            "Minutes last 14": minutes14,
            "Minutes trend": (
                "Unavailable" if minutes7 is None or minutes14 is None
                else "Up" if minutes7 > minutes14 + 1
                else "Down" if minutes7 < minutes14 - 1
                else "Steady"
            ),
            "Games this week": int(games_map.get(nba_team, 0)),
            "Weighted rating": weighted,
            "Opportunity flag": opportunity_flag(player, opportunity_pool),
        })
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("Weighted rating", ascending=False, na_position="last").reset_index(drop=True)
    return frame


def add_drop_suggestions(waivers, roster_rows, excluded_drop_players=None):
    """Return up to three conservative suggestions with roster warnings."""
    if waivers.empty or not roster_rows:
        return []
    excluded = {str(name).casefold() for name in (excluded_drop_players or [])}
    roster = sorted(
        [row for row in roster_rows if str(row["Player"]).casefold() not in excluded],
        key=lambda r: r["Advice score"] if r["Advice score"] is not None else -1,
    )
    if not roster:
        return []
    centers = sum("C" in row["Eligible"] for row in roster_rows)
    suggestions = []
    for _, add in waivers.dropna(subset=["Weighted rating"]).head(8).iterrows():
        if is_unavailable_status(add.get("Injury status")):
            continue
        if bool(add.get("News injury flag", False)):
            continue
        drop = next((r for r in roster if r["Advice score"] is None or add["Weighted rating"] > r["Advice score"]), None)
        if not drop:
            continue
        warnings = []
        if "C" in str(add["Positions"]).upper().split("/") and centers >= 4 and "C" not in drop["Eligible"]:
            warnings.append("Would exceed the four-center limit.")
        if Counter(p for r in roster_rows if r["Player"] != drop["Player"] for p in r["Eligible"])["PG"] == 0:
            warnings.append("Could leave PG difficult to fill.")
        suggestions.append({
            "Add": add["Player"], "Drop": drop["Player"],
            "Reason": f"{add['Weighted rating']:.1f} weighted rating versus {drop['Advice score'] if drop['Advice score'] is not None else 'no'} recent rating.",
            "Injury status": add.get("Injury status", "Unknown"),
            "Warning": " ".join(warnings) or (
                "Verify availability before claiming."
                if str(add.get("Injury status", "")).upper() not in HEALTHY_STATUSES
                else "No obvious roster-rule warning."
            ),
        })
        if len(suggestions) == 3:
            break
    return suggestions


def team_strengths(rows):
    by_position = {}
    for row in rows:
        score = row["Advice score"]
        if score is None:
            continue
        for pos in row["Eligible"]:
            if pos in {"PG", "SG", "SF", "PF", "C"}:
                by_position.setdefault(pos, []).append(score)
    averages = {pos: sum(values) / len(values) for pos, values in by_position.items() if values}
    if not averages:
        return "Unknown", "Unknown"
    return max(averages, key=averages.get), min(averages, key=averages.get)


def injury_pool_from_league(league):
    """Collect league-rostered players for teammate opportunity checks."""
    return [player for team in getattr(league, "teams", []) for player in getattr(team, "roster", [])]


def opportunity_flag(player, injury_pool):
    """Flag an injured teammate who competes at at least one position."""
    team = normalize_nba_team(getattr(player, "proTeam", ""))
    positions = set(player_positions(player))
    matches = []
    for teammate in injury_pool:
        if getattr(teammate, "playerId", None) == getattr(player, "playerId", None):
            continue
        if normalize_nba_team(getattr(teammate, "proTeam", "")) != team:
            continue
        status = str(getattr(teammate, "injuryStatus", "") or "").upper()
        if status in HEALTHY_STATUSES or not positions.intersection(player_positions(teammate)):
            continue
        matches.append(f"{teammate.name} ({status})")
    if not matches:
        return ""
    return "Possible role/minutes boost: competing teammate " + ", ".join(matches[:2])


def is_unavailable_status(status):
    """Return True when ESPN says a player should not be recommended to add/start."""
    normalized = str(status or "").upper().replace("_", " ").strip()
    return normalized in INACTIVE_STATUSES or normalized.startswith("OUT")


def weekly_lineup_plan(league, team, schedule, previous_league=None, base_rows=None):
    """Return a legal lineup recommendation for every day of the matchup week."""
    plans = {}
    # Every tab uses only information known today; future results are never assumed.
    if base_rows is None:
        base_rows = build_player_rows(league, team, set(), date.today(), previous_league)
    current = schedule["start_date"]
    while current <= schedule["end_date"]:
        games = schedule["games"]
        day_games = games[games["game_date"] == current]
        playing = set(day_games["homeTeam_teamTricode"]) | set(day_games["awayTeam_teamTricode"])
        rows = [{**row, "Game today": row["NBA team"] in playing} for row in base_rows]
        plans[current] = recommend_lineup(rows)
        current += timedelta(days=1)
    return plans
