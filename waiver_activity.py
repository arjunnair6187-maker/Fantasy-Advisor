"""Read-only access to the authenticated owner's ESPN waiver activity."""

from datetime import datetime


ACTIVE_STATUSES = {"PENDING", "PROPOSED"}


def _team_transactions(league, team_id):
    """Read and reconcile ESPN's append-only waiver transaction history."""
    scoring_period = int(
        getattr(league, "scoringPeriodId", 0)
        or getattr(league, "current_week", 1)
        or 1
    )
    data = league.espn_request.get_league_offers(scoring_period)
    transactions = [
        transaction for transaction in data.get("transactions", [])
        if int(transaction.get("teamId", -1)) == int(team_id)
    ]
    # ESPN cancellation is a new row. The original row can continue to say
    # PENDING, so its id must be suppressed via relatedTransactionId.
    canceled_ids = {
        transaction.get("relatedTransactionId")
        for transaction in transactions
        if (
            str(transaction.get("executionType", "")).upper() == "CANCEL"
            or str(transaction.get("status", "")).upper() == "CANCELED"
        )
        and transaction.get("relatedTransactionId")
    }
    active = [
        transaction for transaction in transactions
        if str(transaction.get("status", "")).upper() in ACTIVE_STATUSES
        and transaction.get("id") not in canceled_ids
    ]
    recent = [
        transaction for transaction in transactions
        if str(transaction.get("status", "")).upper() not in ACTIVE_STATUSES
    ]
    return active, recent


def _player_name(league, player_id):
    mapped = getattr(league, "player_map", {}).get(player_id)
    if mapped is not None:
        return str(getattr(mapped, "name", mapped))
    for team in getattr(league, "teams", []):
        for player in getattr(team, "roster", []):
            if getattr(player, "playerId", None) == player_id:
                return player.name
    return f"ESPN player {player_id}"


def _move_row(league, transaction):
    added, dropped = [], []
    for item in transaction.get("items") or []:
        name = _player_name(league, item.get("playerId"))
        if str(item.get("type", "")).upper() == "ADD":
            added.append(name)
        elif str(item.get("type", "")).upper() == "DROP":
            dropped.append(name)
    timestamp = (
        transaction.get("processDate")
        or transaction.get("acceptedDate")
        or transaction.get("proposedDate")
    )
    process_time = "Not supplied by ESPN"
    if timestamp:
        process_time = datetime.fromtimestamp(timestamp / 1000).strftime(
            "%a %b %d at %I:%M %p"
        )
    bid = transaction.get("bidAmount")
    priority = transaction.get("priority")
    return {
        "Status": str(transaction.get("status", "Unknown")).replace("_", " ").title(),
        "Move type": str(transaction.get("type", "Waiver")).replace("_", " ").title(),
        "Add": ", ".join(added) or "—",
        "Drop": ", ".join(dropped) or "—",
        "Claim priority": "—" if priority is None else int(priority),
        "Bid": "—" if bid is None else bid,
        "Processes": process_time,
    }


def waiver_activity(league, team_id):
    """Return active and recent waiver rows for one team without mutating ESPN."""
    active, recent = _team_transactions(league, team_id)
    return (
        [_move_row(league, transaction) for transaction in active],
        [_move_row(league, transaction) for transaction in recent[:10]],
    )


def active_waiver_claims(league, team_id):
    """Return structured pending claims in ESPN priority order."""
    active, _ = _team_transactions(league, team_id)
    claims = []
    for transaction in active:
        added, dropped = [], []
        for item in transaction.get("items") or []:
            name = _player_name(league, item.get("playerId"))
            if str(item.get("type", "")).upper() == "ADD":
                added.append(name)
            elif str(item.get("type", "")).upper() == "DROP":
                dropped.append(name)
        claims.append({
            "Add": added[0] if added else None,
            "Drop": dropped[0] if dropped else None,
            "Priority": transaction.get("priority"),
        })
    return sorted(
        claims,
        key=lambda claim: claim["Priority"] if claim["Priority"] is not None else 999,
    )
