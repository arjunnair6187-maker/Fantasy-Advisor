"""Read-only connection to the private ESPN fantasy league."""

from typing import Any
from datetime import date

from espn_api.basketball import League


ESPN_SEASON_YEAR = 2027
ESPN_NFL_SEASON_YEAR = date.today().year


def _validated_connection(credentials, league_id):
    if not isinstance(credentials, dict):
        raise ValueError("A user-owned ESPN credential connection is required.")
    espn_s2 = str(credentials.get("espn_s2", "")).strip()
    swid = str(credentials.get("swid", "")).strip()
    league_id = str(league_id or credentials.get("league_id", "")).strip()
    if not espn_s2 or not swid:
        raise ValueError("Both required ESPN cookies must be provided by this user's connection.")
    if not league_id.isdigit():
        raise ValueError("The ESPN league ID must contain only numbers.")
    return int(league_id), espn_s2, swid


def connect_to_league(
    year: int = ESPN_SEASON_YEAR,
    credentials: dict[str, Any] | None = None,
    league_id: str | int | None = None,
) -> League:
    """Connect read-only using credentials supplied for one user's league."""
    league_id, espn_s2, swid = _validated_connection(credentials, league_id)

    return League(
        league_id=league_id,
        year=year,
        espn_s2=espn_s2,
        swid=swid,
        debug=False,
    )


def connect_to_nfl_league(
    year: int = ESPN_NFL_SEASON_YEAR,
    credentials: dict[str, Any] | None = None,
    league_id: str | int | None = None,
):
    """Connect read-only to one user's ESPN fantasy football league."""
    from espn_api.football import League as FootballLeague

    league_id, espn_s2, swid = _validated_connection(credentials, league_id)
    return FootballLeague(
        league_id=league_id,
        year=year,
        espn_s2=espn_s2,
        swid=swid,
        debug=False,
    )
