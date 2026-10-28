"""Player metrics calculated only from completed NBA box scores."""

from collections.abc import Mapping
from datetime import date, datetime, timedelta

from scoring import calculate_fantasy_points


def _stat_group(player, year, suffix):
    """Find an ESPN season stat group even if its key is stored as text."""
    wanted = f"{year}_{suffix}".casefold()
    for key, value in getattr(player, "stats", {}).items():
        if str(key).casefold() == wanted and isinstance(value, Mapping):
            return value
    return {}


def espn_applied_average(player, year, projected=False):
    """Return ESPN's league-settings FP/G for a projected or actual season."""
    group = _stat_group(player, year, "projected" if projected else "total")
    value = group.get("applied_avg")
    try:
        return None if value is None else round(float(value), 2)
    except (TypeError, ValueError):
        return None


def blended_projection(player, season_year=2027, previous_player=None):
    """Blend current ESPN projection with the prior season's real FP/G."""
    espn_projection = espn_applied_average(player, season_year, projected=True)
    prior = (
        espn_applied_average(previous_player, season_year - 1, projected=False)
        if previous_player is not None else None
    )
    if espn_projection is not None and prior is not None:
        blended = round(0.70 * espn_projection + 0.30 * prior, 2)
        basis = "70% ESPN projection + 30% last season"
    elif espn_projection is not None:
        blended = espn_projection
        basis = "ESPN projection only"
    elif prior is not None:
        blended = prior
        basis = "Last season only"
    else:
        blended = None
        basis = "Unavailable"
    return {
        "espn_projection": espn_projection,
        "previous_fppg": prior,
        "blended_fppg": blended,
        "projection_basis": basis,
    }


def _game_records(player):
    """Return dated custom scores from real game-level records."""

    records = []

    for stat_group in getattr(player, "stats", {}).values():
        if not isinstance(stat_group, Mapping):
            continue

        game_date = stat_group.get("date")
        box_score = stat_group.get("total")

        if game_date is None or not isinstance(box_score, Mapping):
            continue

        if isinstance(game_date, datetime):
            game_date = game_date.date()
        elif not isinstance(game_date, date):
            try:
                game_date = datetime.fromisoformat(
                    str(game_date).replace("Z", "+00:00")
                ).date()
            except ValueError:
                continue

        records.append(
            (game_date, calculate_fantasy_points(box_score))
        )

    return records


def game_score_records(player):
    """Public copy of completed-game dates and custom fantasy scores."""
    return list(_game_records(player))


def custom_fppg_from_espn_player(player):
    """
    Return (custom FP/G, games counted).

    ESPN projections and season summaries are deliberately ignored.
    Only dated, game-level box scores are used.
    """

    scores = [score for _, score in _game_records(player)]

    if not scores:
        return None, 0

    average = sum(scores) / len(scores)
    return round(average, 2), len(scores)


def rolling_custom_fppg(player, days, reference_date=None):
    """Return custom FP/G and games played within a recent-day window."""

    if reference_date is None:
        reference_date = date.today()

    start_date = reference_date - timedelta(days=days - 1)

    scores = [
        score
        for game_date, score in _game_records(player)
        if start_date <= game_date <= reference_date
    ]

    if not scores:
        return None, 0

    return round(sum(scores) / len(scores), 2), len(scores)


def rolling_stat_average(player, stat_name, days, reference_date=None):
    """Average one supplied box-score stat over a recent window."""
    if reference_date is None:
        reference_date = date.today()
    start_date = reference_date - timedelta(days=days - 1)
    values = []
    for stat_group in getattr(player, "stats", {}).values():
        if not isinstance(stat_group, Mapping):
            continue
        game_date = stat_group.get("date")
        box_score = stat_group.get("total")
        if game_date is None or not isinstance(box_score, Mapping):
            continue
        if isinstance(game_date, datetime):
            game_date = game_date.date()
        elif not isinstance(game_date, date):
            try:
                game_date = datetime.fromisoformat(str(game_date).replace("Z", "+00:00")).date()
            except ValueError:
                continue
        value = box_score.get(stat_name)
        if start_date <= game_date <= reference_date and value is not None:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                pass
    return None if not values else round(sum(values) / len(values), 1)
