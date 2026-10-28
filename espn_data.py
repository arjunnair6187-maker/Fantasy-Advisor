"""Read-only connection to the private ESPN fantasy league."""

from typing import Any

from espn_api.basketball import League


ESPN_SEASON_YEAR = 2027


def connect_to_league(
    year: int = ESPN_SEASON_YEAR,
    credentials: dict[str, Any] | None = None,
    league_id: str | int | None = None,
) -> League:
    """Connect read-only using credentials supplied for one user's league."""
    if not isinstance(credentials, dict):
        raise ValueError("A user-owned ESPN credential connection is required.")

    espn_s2 = str(credentials.get("espn_s2", "")).strip()
    swid = str(credentials.get("swid", "")).strip()
    league_id = str(league_id or credentials.get("league_id", "")).strip()

    if not espn_s2 or not swid:
        raise ValueError("Both required ESPN cookies must be provided by this user's connection.")
    if not league_id.isdigit():
        raise ValueError("The ESPN league ID must contain only numbers.")

    return League(
        league_id=int(league_id),
        year=year,
        espn_s2=espn_s2,
        swid=swid,
        debug=False,
    )
