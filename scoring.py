"""One source of truth for the league's custom scoring."""

from collections.abc import Mapping


def _number(stats: Mapping, *names: str) -> float:
    """Return the first matching stat value, or zero when unavailable."""
    for name in names:
        value = stats.get(name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def calculate_fantasy_points(stats: Mapping) -> float:
    """Calculate fantasy points for one real NBA game."""

    pts = _number(stats, "PTS")
    reb = _number(stats, "REB")
    ast = _number(stats, "AST")
    stl = _number(stats, "STL")
    blk = _number(stats, "BLK")
    turnovers = _number(stats, "TO", "TOV")
    threes = _number(stats, "3PM", "3PTM")
    ftm = _number(stats, "FTM")
    fta = _number(stats, "FTA")

    # Derive double/triple/quadruple-doubles from the box score.
    double_digit_categories = sum(
        value >= 10 for value in (pts, reb, ast, stl, blk)
    )
    double_double = 1 if double_digit_categories >= 2 else 0
    triple_double = 1 if double_digit_categories >= 3 else 0
    quadruple_double = 1 if double_digit_categories >= 4 else 0

    # Rare discipline stats are included when the source supplies them.
    flagrant_fouls = _number(stats, "FF", "FLAGRANT_FOULS")
    ejections = _number(stats, "EJ", "EJECTIONS")
    disqualifications = _number(stats, "DQ", "DISQUALIFICATIONS")

    score = (
        pts
        + reb
        + 2 * ast
        + 2 * stl
        + 2 * blk
        - 2 * turnovers
        + 0.5 * threes
        + ftm
        - fta
        + double_double
        + 2 * triple_double
        + 5 * quadruple_double
        - 0.5 * flagrant_fouls
        - 3 * ejections
        - 5 * disqualifications
    )

    return round(score, 2)


RARE_STATS_WARNING = (
    "Flagrant fouls, ejections, and disqualifications are counted when the "
    "data source provides them. Missing rare-event fields are treated as zero."
)