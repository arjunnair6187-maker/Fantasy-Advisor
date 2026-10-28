"""Weekly player and team projections using custom fantasy points."""

import pandas as pd

from player_metrics import blended_projection


TEAM_ABBREVIATION_MAP = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "PHO": "PHX",
    "PHL": "PHI",
    "SA": "SAS",
    "WSH": "WAS",
    "UTAH": "UTA",
    "PHILA": "PHI",
    "NY KNICKS": "NYK",
    "LA CLIPPERS": "LAC",
    "LA LAKERS": "LAL",
}


def normalize_nba_team(team_code):
    """Convert ESPN team abbreviations to NBA schedule abbreviations."""
    code = str(team_code or "").upper().strip()
    return TEAM_ABBREVIATION_MAP.get(code, code)


def _display_positions(player):
    order = ["PG", "SG", "SF", "PF", "C"]
    found = []
    for value in [getattr(player, "position", ""), *(getattr(player, "eligibleSlots", None) or [])]:
        for part in str(value).upper().replace("-", "/").split("/"):
            part = part.strip()
            if part in order and part not in found:
                found.append(part)
    return "/".join(sorted(found, key=order.index)) or "Unknown"


def _details_by_id(league, roster):
    if league is None or not roster:
        return {}
    try:
        result = league.player_info(playerId=[player.playerId for player in roster])
        if not isinstance(result, list):
            result = [result]
        return {player.playerId: player for player in result if player is not None}
    except Exception:
        return {}


def projection_rows(league, team, game_counts, previous_league=None):
    """Build reusable player projection rows for one roster."""
    games_by_team = {
        normalize_nba_team(team_code): int(games)
        for team_code, games in zip(game_counts["NBA team"], game_counts["Games"])
    }
    roster = list(team.roster)
    details = _details_by_id(league, roster)
    previous_details = _details_by_id(previous_league, roster)
    rows = []
    for player in roster:
        detail = details.get(player.playerId, player)
        prior = previous_details.get(player.playerId)
        projection = blended_projection(detail, previous_player=prior)
        nba_team = normalize_nba_team(getattr(player, "proTeam", ""))
        games = int(games_by_team.get(nba_team, 0))
        rows.append({
            "Player": player.name,
            "NBA team": nba_team or "Unknown",
            "Positions": _display_positions(player),
            "ESPN projected FP/G": projection["espn_projection"],
            "2025-26 FP/G": projection["previous_fppg"],
            "Blended FP/G": projection["blended_fppg"],
            "Projection basis": projection["projection_basis"],
            "Games this week": games,
            "Projected week (all games)": None if projection["blended_fppg"] is None else round(projection["blended_fppg"] * games, 2),
            "_player": player,
            "_detail": detail,
        })
    return rows


def project_team_for_week(league, team, game_counts, previous_league=None):
    """
    Project every rostered player's week.

    Player table uses the ESPN/current-plus-prior-season blended FP/G.
    """

    rows = projection_rows(league, team, game_counts, previous_league)

    columns = [
        "Player",
        "NBA team",
        "Positions",
        "ESPN projected FP/G",
        "2025-26 FP/G",
        "Blended FP/G",
        "Projection basis",
        "Games this week",
        "Projected week (all games)",
    ]
    table = pd.DataFrame([{key: row.get(key) for key in columns} for row in rows], columns=columns)

    if table.empty:
        return table, None, 0

    available = table["Projected week (all games)"].dropna()
    missing_players = int(table["Projected week (all games)"].isna().sum())

    total = (
        None
        if available.empty
        else round(float(available.sum()), 2)
    )

    return table, total, missing_players
