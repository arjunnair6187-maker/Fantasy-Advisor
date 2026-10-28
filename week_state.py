"""Reconcile ESPN matchup periods with the dated NBA schedule."""


def effective_matchup_period(league, schedule=None):
    """Return the active fantasy period, advancing stale ESPN regular weeks."""
    reported = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    if not schedule or schedule.get("status") != "current":
        return reported
    schedule_week = schedule.get("week_number")
    if schedule_week is None:
        return reported
    try:
        schedule_week = int(schedule_week)
    except (TypeError, ValueError):
        return reported
    regular_periods = getattr(
        getattr(league, "settings", None), "reg_season_count", None
    )
    # NBA calendar Week N and ESPN matchup period N align during this league's
    # one-week regular-season matchups. Playoff periods last two weeks, so the
    # schedule clock must not override ESPN after the regular season.
    if regular_periods is not None:
        regular_periods = int(regular_periods)
        if reported > regular_periods or schedule_week > regular_periods:
            return reported
    return max(reported, schedule_week)
