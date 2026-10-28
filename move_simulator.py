"""Counterfactual add/drop simulation using legal daily fantasy lineups."""

from datetime import timedelta

import pandas as pd

from advice_engine import recommend_lineup


def _week_total(rows, schedule):
    total = 0.0
    starts = 0
    current = schedule["start_date"]
    while current <= schedule["end_date"]:
        games = schedule["games"]
        day_games = games[games["game_date"] == current]
        playing = set(day_games["homeTeam_teamTricode"]) | set(
            day_games["awayTeam_teamTricode"]
        )
        daily_rows = [
            {**row, "Game today": row["NBA team"] in playing} for row in rows
        ]
        for recommendation in recommend_lineup(daily_rows):
            if str(recommendation["Recommendation"]).startswith("Start"):
                total += float(recommendation.get("Advice score") or 0)
                starts += 1
        current += timedelta(days=1)
    return round(total, 1), starts


def simulate_add_drop(base_rows, add_row, drop_name, schedules):
    """Compare current and proposed rosters across supplied schedule weeks."""
    remaining = [row for row in base_rows if row["Player"] != drop_name]
    if len(remaining) == len(base_rows):
        raise ValueError("The selected drop player is not on the roster.")
    proposed = remaining + [add_row]
    weekly = []
    for index, schedule in enumerate(schedules, 1):
        current_total, current_starts = _week_total(base_rows, schedule)
        proposed_total, proposed_starts = _week_total(proposed, schedule)
        weekly.append({
            "Horizon week": index,
            "Dates": f"{schedule['start_date']:%b %d}–{schedule['end_date']:%b %d}",
            "Current roster": current_total,
            "After move": proposed_total,
            "Point change": round(proposed_total - current_total, 1),
            "Current usable games": current_starts,
            "After usable games": proposed_starts,
            "Usable-game change": proposed_starts - current_starts,
        })
    drop = next(row for row in base_rows if row["Player"] == drop_name)
    add_projection = add_row.get("Projected FP/G")
    drop_projection = drop.get("Projected FP/G")
    season_delta = None
    if add_projection is not None and drop_projection is not None:
        season_delta = round(float(add_projection) - float(drop_projection), 1)
    centers = sum("C" in row.get("Eligible", []) for row in proposed)
    position_counts = {
        position: sum(position in row.get("Eligible", []) for row in proposed)
        for position in ["PG", "SG", "SF", "PF", "C"]
    }
    warnings = []
    if centers > 4:
        warnings.append("This move would exceed the four-center limit.")
    missing = [position for position, count in position_counts.items() if count == 0]
    if missing:
        warnings.append("No eligible player remains at: " + ", ".join(missing) + ".")
    return pd.DataFrame(weekly), season_delta, position_counts, warnings


def horizon_totals(weekly):
    """Aggregate weekly scenario deltas into the product's standard horizons."""
    if weekly.empty:
        return pd.DataFrame()
    rows = []
    for label, count in [("1 week", 1), ("2 weeks", 2), ("4 weeks", 4)]:
        window = weekly.head(count)
        rows.append({
            "Horizon": label,
            "Current points": round(float(window["Current roster"].sum()), 1),
            "After move": round(float(window["After move"].sum()), 1),
            "Projected change": round(float(window["Point change"].sum()), 1),
            "Usable-game change": int(window["Usable-game change"].sum()),
        })
    return pd.DataFrame(rows)


def rank_streaming_moves(base_rows, waiver_rows, schedules, protected_drops=None,
                         max_drop_candidates=5):
    """Rank add/drop combinations by legal-lineup gains across multiple weeks."""
    protected = {str(name).casefold() for name in (protected_drops or [])}
    drop_pool = sorted(
        [row for row in base_rows if str(row["Player"]).casefold() not in protected],
        key=lambda row: row["Advice score"] if row["Advice score"] is not None else -1,
    )[:max_drop_candidates]
    # The current roster is identical for every possible move. Calculate it
    # once per week instead of repeating it for every add/drop combination.
    current_weeks = [_week_total(base_rows, schedule) for schedule in schedules]
    base_centers = sum("C" in row.get("Eligible", []) for row in base_rows)
    results = []
    for add_row in waiver_rows:
        for drop in drop_pool:
            proposed = [
                row for row in base_rows if row["Player"] != drop["Player"]
            ] + [add_row]
            centers = sum("C" in row.get("Eligible", []) for row in proposed)
            # ESPN can expose five C-eligible players because secondary
            # eligibility does not always match the league's roster-limit
            # accounting. Block only a move that makes the situation worse.
            if centers > 4 and centers > base_centers:
                continue
            missing = [
                position for position in ["PG", "SG", "SF", "PF", "C"]
                if not any(position in row.get("Eligible", []) for row in proposed)
            ]
            warnings = (
                ["No eligible player remains at: " + ", ".join(missing) + "."]
                if missing else []
            )
            changes = []
            usable = []
            for schedule, (current_total, current_starts) in zip(
                schedules, current_weeks
            ):
                proposed_total, proposed_starts = _week_total(proposed, schedule)
                changes.append(round(proposed_total - current_total, 1))
                usable.append(proposed_starts - current_starts)
            add_projection = add_row.get("Projected FP/G")
            drop_projection = drop.get("Projected FP/G")
            season_delta = None
            if add_projection is not None and drop_projection is not None:
                season_delta = round(
                    float(add_projection) - float(drop_projection), 1
                )
            results.append({
                "Add": add_row["Player"],
                "Drop": drop["Player"],
                "Week 1 gain": changes[0] if changes else 0.0,
                "Week 2 gain": changes[1] if len(changes) > 1 else 0.0,
                "2-week gain": round(sum(changes[:2]), 1),
                "4-week gain": round(sum(changes[:4]), 1),
                "Usable games gained": int(sum(usable[:2])),
                "Season FP/G change": season_delta,
                "Warnings": " ".join(warnings) if warnings else "None",
            })
    frame = pd.DataFrame(results)
    if frame.empty:
        return frame
    return frame.sort_values(
        ["2-week gain", "4-week gain", "Season FP/G change"],
        ascending=[False, False, False], na_position="last",
    ).reset_index(drop=True)
