"""Explainable league strategy, power ranking, draft, and risk models."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date
import math
import statistics

import pandas as pd

from advice_engine import (
    HEALTHY_STATUSES, INACTIVE_STATUSES, build_player_rows, injury_pool_from_league,
    is_unavailable_status, opportunity_flag, player_positions, rank_waivers,
    team_strengths, weekly_lineup_plan,
)
from player_metrics import blended_projection, game_score_records, rolling_stat_average
from projections import normalize_nba_team


def _percentiles(values):
    ordered = sorted(values)
    if len(ordered) <= 1:
        return {value: 0.5 for value in ordered}
    return {
        value: statistics.mean(i for i, candidate in enumerate(ordered) if candidate == value) / (len(ordered) - 1)
        for value in set(ordered)
    }


def _match_score(matchup, side, final=True):
    names = (
        [f"{side}_final_score", f"{side}_score"] if final
        else [f"{side}_live_score", f"{side}_final_score", f"{side}_score"]
    )
    for name in names:
        value = getattr(matchup, name, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return None


def _elo_history(league):
    ratings = {team.team_id: 1500.0 for team in league.teams}
    records = {
        team.team_id: {"wins": 0, "losses": 0, "ties": 0, "points": 0.0, "weeks": 0}
        for team in league.teams
    }
    rank_history = []
    current_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    for period in range(1, current_period):
        try:
            matchups = league.scoreboard(matchupPeriod=period)
        except Exception:
            continue
        for matchup in matchups:
            home, away = matchup.home_team, matchup.away_team
            hs, aws = _match_score(matchup, "home"), _match_score(matchup, "away")
            if hs is None or aws is None or hs == aws == 0:
                continue
            records[home.team_id]["points"] += hs
            records[away.team_id]["points"] += aws
            records[home.team_id]["weeks"] += 1
            records[away.team_id]["weeks"] += 1
            if hs > aws:
                records[home.team_id]["wins"] += 1
                records[away.team_id]["losses"] += 1
            elif hs < aws:
                records[away.team_id]["wins"] += 1
                records[home.team_id]["losses"] += 1
            else:
                records[home.team_id]["ties"] += 1
                records[away.team_id]["ties"] += 1
            expected_home = 1 / (1 + 10 ** ((ratings[away.team_id] - ratings[home.team_id]) / 400))
            actual_home = 1.0 if hs > aws else 0.0 if hs < aws else 0.5
            margin_factor = min(2.0, 1 + abs(hs - aws) / max(200.0, (hs + aws) / 2))
            change = 24 * margin_factor * (actual_home - expected_home)
            ratings[home.team_id] += change
            ratings[away.team_id] -= change
        ranked = sorted(ratings, key=ratings.get, reverse=True)
        rank_history.append({team_id: i + 1 for i, team_id in enumerate(ranked)})
    return ratings, rank_history, records


def league_power_rankings(league, previous_league=None):
    """Blend roster quality with opponent-adjusted weekly results."""
    team_rows, roster_strength = {}, {}
    all_players = [player for team in league.teams for player in team.roster]
    details, previous_details = {}, {}
    if all_players:
        ids = [player.playerId for player in all_players]
        try:
            result = league.player_info(playerId=ids)
            if not isinstance(result, list):
                result = [result]
            details = {player.playerId: player for player in result if player is not None}
        except Exception:
            pass
        if previous_league is not None:
            try:
                result = previous_league.player_info(playerId=ids)
                if not isinstance(result, list):
                    result = [result]
                previous_details = {player.playerId: player for player in result if player is not None}
            except Exception:
                pass
    for team in league.teams:
        rows = build_player_rows(
            league, team, set(), previous_league=previous_league,
            details_override=details, previous_details_override=previous_details,
        )
        team_rows[team.team_id] = rows
        values = sorted(
            [float(row["Advice score"]) for row in rows if row["Advice score"] is not None],
            reverse=True,
        )
        roster_strength[team.team_id] = sum(values[:10]) + 0.35 * sum(values[10:13])
    elo, history, completed_records = _elo_history(league)
    # The preseason/draft-day baseline is roster quality before weekly results
    # begin moving teams up or down.
    draft_order = sorted(roster_strength, key=roster_strength.get, reverse=True)
    draft_ranks = {team_id: rank for rank, team_id in enumerate(draft_order, 1)}
    roster_pct = _percentiles(list(roster_strength.values()))
    elo_pct = _percentiles(list(elo.values()))
    completed = len(history)
    results_weight = min(0.60, completed * 0.10)
    rows = []
    for team in league.teams:
        tid = team.team_id
        overall = 100 * ((1 - results_weight) * roster_pct[roster_strength[tid]] + results_weight * elo_pct[elo[tid]])
        players = sorted(
            team_rows[tid], key=lambda row: row["Advice score"] if row["Advice score"] is not None else -1,
            reverse=True,
        )
        star_values = [p["Advice score"] for p in players[:3] if p["Advice score"] is not None]
        depth_values = [p["Advice score"] for p in players[8:13] if p["Advice score"] is not None]
        star = statistics.mean(star_values) if star_values else 0
        depth = statistics.mean(depth_values) if depth_values else 0
        strongest, weakest = team_strengths(team_rows[tid])
        injured = sum(str(p["Injury status"]).upper() not in HEALTHY_STATUSES for p in players)
        simple = (
            f"Elite top-end talent led by {players[0]['Player']}, but depth is the main concern."
            if star >= 1.25 * max(depth, 1)
            else f"A balanced roster with useful depth; {weakest} is the clearest area to improve."
        )
        technical = (
            f"Roster index {roster_strength[tid]:.1f}; opponent-adjusted rating {elo[tid]:.0f}; "
            f"top-three average {star:.1f} FP/G; depth average {depth:.1f} FP/G; {injured} injury flags."
        )
        previous_rank = history[-1].get(tid) if history else None
        completed = completed_records[tid]
        rows.append({
            "Team ID": tid, "Team": team.team_name, "Power score": round(overall, 1),
            "Record": f"{completed['wins']}-{completed['losses']}-{completed['ties']}",
            "Points/week": (
                None if not completed["weeks"]
                else round(completed["points"] / completed["weeks"], 1)
            ),
            "Elo": round(elo[tid]),
            "Draft rank": draft_ranks[tid],
            "Roster index": round(roster_strength[tid], 1), "Strongest": strongest,
            "Weakest": weakest, "Injury flags": injured, "Previous rank": previous_rank,
            "Technical analysis": technical, "Plain-English assessment": simple,
        })
    rows.sort(key=lambda row: row["Power score"], reverse=True)
    for index, row in enumerate(rows, 1):
        row["Rank"] = index
        previous = row.pop("Previous rank")
        row["Movement"] = "NEW" if previous is None else "—" if previous == index else f"▲ {previous-index}" if previous > index else f"▼ {index-previous}"
        row["Tier"] = "Contender" if index <= 3 else "Playoff mix" if index <= 6 else "Needs improvement"
    history_rows = []
    names = {team.team_id: team.team_name for team in league.teams}
    for week_index, ranks in enumerate(history, 1):
        for tid, rank in ranks.items():
            history_rows.append({"Week": week_index, "Team": names[tid], "Rank": rank})
    return pd.DataFrame(rows), pd.DataFrame(history_rows), team_rows


def strategy_plan(power, my_team_name):
    mine = power[power["Team"] == my_team_name]
    if mine.empty:
        return []
    row = mine.iloc[0]
    return [
        {"Horizon": "1 week", "Priority": "Protect active points", "Action": "Recheck injury designations, pending claims, and every legal lineup slot before the first tipoff."},
        {"Horizon": "2 weeks", "Priority": f"Improve {row['Weakest']} depth", "Action": f"Compare the best available {row['Weakest']} players with your final bench spots and both upcoming matchup schedules."},
        {"Horizon": "4 weeks", "Priority": "Build flexibility", "Action": "Prefer multi-position players and pursue a starter upgrade if the four-week outlook falls below break-even."},
        {"Horizon": "Season", "Priority": "Raise playoff ceiling", "Action": f"Your current tier is {row['Tier']}. Pursue rest-of-season upgrades that improve top-10 starting value, not cosmetic bench swaps."},
    ]


def quantified_strategy_moves(league, team, power, team_rows, game_counts,
                              previous_league=None, pending_claims=None):
    """Turn positional weaknesses into measurable waiver and trade options."""
    positions = ["PG", "SG", "SF", "PF", "C"]
    my_rows = list(team_rows.get(team.team_id, []))
    games_map = {
        normalize_nba_team(code): int(games)
        for code, games in zip(game_counts["NBA team"], game_counts["Games"])
    }

    def position_average(rows, position, score_key="Advice score"):
        values = [float(row[score_key]) for row in rows
                  if position in row["Eligible"] and row.get(score_key) is not None
                  and pd.notna(row.get(score_key))]
        return statistics.mean(values) if values else 0.0

    injury_pool = injury_pool_from_league(league)
    waivers = rank_waivers(
        league, game_counts, size=75, previous_league=previous_league,
        injury_pool=injury_pool,
    )

    # Build the roster we expect after the highest-priority non-conflicting
    # waiver claims succeed. Claims sharing the same drop are alternatives.
    provisional_rows = list(my_rows)
    applied_claims = []
    claimed_names = {
        str(claim.get("Add", "")).casefold() for claim in (pending_claims or [])
        if claim.get("Add")
    }
    pending_drop_names = {
        str(claim.get("Drop", "")).casefold() for claim in (pending_claims or [])
        if claim.get("Drop")
    }
    for claim in pending_claims or []:
        add_name, drop_name = claim.get("Add"), claim.get("Drop")
        if not add_name:
            continue
        add_match = waivers[waivers["Player"].astype(str).str.casefold() == str(add_name).casefold()]
        if add_match.empty:
            continue
        if pd.isna(add_match.iloc[0]["Weighted rating"]):
            continue
        if drop_name:
            drop_index = next(
                (index for index, row in enumerate(provisional_rows)
                 if str(row["Player"]).casefold() == str(drop_name).casefold()),
                None,
            )
            if drop_index is None:
                continue
            provisional_rows.pop(drop_index)
        add = add_match.iloc[0]
        provisional_rows.append({
            "Player": add["Player"],
            "Eligible": str(add["Positions"]).split("/"),
            "Advice score": add["Weighted rating"],
            "Projected FP/G": add["Projected FP/G"],
            "NBA team": add["NBA team"],
            "Injury status": add["Injury status"],
        })
        applied_claims.append({
            "Pending add": add["Player"],
            "Pending drop": drop_name or "Open roster spot",
            "Priority": claim.get("Priority") if claim.get("Priority") is not None else "—",
            "Projected FP/G": round(float(add["Weighted rating"]), 1),
            "Positions added": add["Positions"],
        })
    analysis_team_rows = dict(team_rows)
    analysis_team_rows[team.team_id] = provisional_rows
    my_rows = provisional_rows

    league_averages = {}
    long_league_averages = {}
    for position in positions:
        values = [
            position_average(rows, position) for rows in analysis_team_rows.values()
            if position_average(rows, position) > 0
        ]
        league_averages[position] = statistics.mean(values) if values else 0.0
        long_values = [
            position_average(rows, position, "Projected FP/G")
            for rows in analysis_team_rows.values()
            if position_average(rows, position, "Projected FP/G") > 0
        ]
        long_league_averages[position] = statistics.mean(long_values) if long_values else 0.0
    weakness_rows = []
    for position in positions:
        mine = position_average(my_rows, position)
        long_mine = position_average(my_rows, position, "Projected FP/G")
        team_values = sorted(
            [(position_average(rows, position), tid) for tid, rows in analysis_team_rows.items()],
            reverse=True,
        )
        rank = next((index + 1 for index, (_, tid) in enumerate(team_values)
                     if tid == team.team_id), len(team_values))
        eligible = sorted(
            [row for row in my_rows if position in row["Eligible"]],
            key=lambda row: row["Advice score"] if row["Advice score"] is not None else -1,
        )
        weakest = eligible[0] if eligible else None
        gap = mine - league_averages[position]
        long_gap = long_mine - long_league_averages[position]
        weakness_rows.append({
            "Position": position, "Short-term FP/G": round(mine, 1),
            "Short-term gap": round(gap, 1),
            "Short-term status": "Addressed" if gap >= -1 else "Still weak",
            "Long-term FP/G": round(long_mine, 1),
            "Long-term gap": round(long_gap, 1),
            "Long-term status": "On track" if long_gap >= -1 else "Needs upgrade",
            "League average": round(league_averages[position], 1),
            "League rank": f"{rank}/{len(team_values)}",
            "Weakest current option": weakest["Player"] if weakest else "Unfilled",
            "Weakest option FP/G": None if weakest is None else weakest["Advice score"],
        })
    weaknesses = pd.DataFrame(weakness_rows).sort_values("Short-term gap")
    focus_positions = weaknesses.head(2)["Position"].tolist()
    long_focus_positions = weaknesses.sort_values("Long-term gap").head(2)["Position"].tolist()

    current_centers = sum("C" in row["Eligible"] for row in my_rows)
    waiver_moves = []
    for position in focus_positions:
        eligible_roster = sorted(
            [row for row in my_rows if position in row["Eligible"]
             and str(row["Player"]).casefold() not in pending_drop_names],
            key=lambda row: row["Advice score"] if row["Advice score"] is not None else -1,
        )
        eligible_drops = [
            row for row in my_rows
            if str(row["Player"]).casefold() not in pending_drop_names
        ]
        if not eligible_drops:
            continue
        drop = eligible_roster[0] if eligible_roster else min(
            eligible_drops,
            key=lambda row: row["Advice score"] if row["Advice score"] is not None else -1,
        )
        drop_score = float(drop["Advice score"] or 0)
        drop_games = games_map.get(drop["NBA team"], 0)
        candidates = waivers[
            waivers["Positions"].astype(str).str.split("/").apply(lambda values: position in values)
            & (~waivers["Injury status"].apply(is_unavailable_status))
            & (~waivers["Player"].astype(str).str.casefold().isin(claimed_names))
        ]
        for _, add in candidates.head(8).iterrows():
            if pd.isna(add["Weighted rating"]):
                continue
            add_score = float(add["Weighted rating"])
            weekly_gain = add_score * int(add["Games this week"]) - drop_score * drop_games
            if add_score <= drop_score and weekly_gain <= 0:
                continue
            add_positions = str(add["Positions"]).split("/")
            if "C" in add_positions and current_centers >= 4 and "C" not in drop["Eligible"]:
                continue
            remaining_positions = {
                pos for row in my_rows if row["Player"] != drop["Player"] for pos in row["Eligible"]
            }
            rule_check = "Passes four-center check"
            if any(pos not in remaining_positions and pos not in add_positions for pos in ["PG", "SG", "SF", "PF", "C"]):
                rule_check = "Review slot coverage before claiming"
            waiver_moves.append({
                "Fixes": position, "Add": add["Player"], "Drop": drop["Player"],
                "Add FP/G": round(add_score, 1), "Drop FP/G": round(drop_score, 1),
                "FP/G gain": round(add_score - drop_score, 1),
                "This-week gain": round(weekly_gain, 1),
                "Add games": int(add["Games this week"]), "Drop games": drop_games,
                "Injury status": add["Injury status"],
                "Opportunity": add.get("Opportunity flag", ""),
                "Roster-rule check": rule_check,
                "Recommendation": "Claim" if add_score - drop_score >= 2 or weekly_gain >= 8 else "Watch",
            })
    waiver_frame = pd.DataFrame(waiver_moves)
    if not waiver_frame.empty:
        waiver_frame = waiver_frame.sort_values(
            ["Recommendation", "This-week gain", "FP/G gain"],
            ascending=[True, False, False],
        ).drop_duplicates("Add").head(5)

    long_term_moves = []
    for position in long_focus_positions:
        roster_options = [
            row for row in my_rows
            if position in row["Eligible"] and row.get("Projected FP/G") is not None
        ]
        weakest_long = min(
            roster_options, key=lambda row: row["Projected FP/G"]
        ) if roster_options else None
        baseline = float(weakest_long["Projected FP/G"] if weakest_long else 0)
        long_candidates = waivers[
            waivers["Positions"].astype(str).str.split("/").apply(lambda values: position in values)
            & (~waivers["Player"].astype(str).str.casefold().isin(claimed_names))
        ].dropna(subset=["Projected FP/G"]).copy()
        long_candidates["Long-term gain"] = long_candidates["Projected FP/G"].astype(float) - baseline
        for _, candidate in long_candidates.sort_values("Long-term gain", ascending=False).head(3).iterrows():
            if float(candidate["Long-term gain"]) <= 0:
                continue
            unavailable = is_unavailable_status(candidate["Injury status"])
            long_term_moves.append({
                "Fixes": position,
                "Target": candidate["Player"],
                "Replace": weakest_long["Player"] if weakest_long else "Open roster spot",
                "Projected FP/G": round(float(candidate["Projected FP/G"]), 1),
                "Long-term gain": round(float(candidate["Long-term gain"]), 1),
                "Health status": candidate["Injury status"],
                "Action": "Monitor return; stash only if roster space allows" if unavailable else "Long-term waiver upgrade",
            })
    long_term_frame = pd.DataFrame(long_term_moves)
    if not long_term_frame.empty:
        long_term_frame = long_term_frame.sort_values(
            "Long-term gain", ascending=False
        ).drop_duplicates("Target").head(6)

    my_strength, _ = team_strengths(my_rows)
    offer_pool = sorted(
        [row for row in my_rows if my_strength in row["Eligible"] and row["Advice score"] is not None
         and str(row["Player"]).casefold() not in pending_drop_names],
        key=lambda row: row["Advice score"], reverse=True,
    )
    trade_moves = []
    for position in focus_positions:
        baseline_candidates = [row for row in my_rows if position in row["Eligible"] and row["Advice score"] is not None]
        baseline = min(baseline_candidates, key=lambda row: row["Advice score"]) if baseline_candidates else None
        baseline_score = float(baseline["Advice score"] if baseline else 0)
        for other in league.teams:
            if other.team_id == team.team_id:
                continue
            other_rows = team_rows.get(other.team_id, [])
            _, their_need = team_strengths(other_rows)
            targets = sorted(
                [row for row in other_rows if position in row["Eligible"] and row["Advice score"] is not None
                 and not is_unavailable_status(row["Injury status"])],
                key=lambda row: row["Advice score"], reverse=True,
            )
            for target in targets:
                target_score = float(target["Advice score"])
                offers = [row for row in offer_pool if 0.82 * target_score <= float(row["Advice score"]) <= 1.12 * target_score]
                if not offers:
                    continue
                offer = min(offers, key=lambda row: abs(float(row["Advice score"]) - target_score))
                remaining = [row for row in offer_pool if row["Player"] != offer["Player"]]
                replacement = float(remaining[0]["Advice score"]) if remaining else 0
                weak_gain = target_score - baseline_score
                surplus_cost = max(0, float(offer["Advice score"]) - replacement)
                net_gain = weak_gain - surplus_cost
                if weak_gain <= 0 or net_gain <= 0:
                    continue
                trade_moves.append({
                    "Fixes": position, "Target": target["Player"], "Target team": other.team_name,
                    "Target FP/G": round(target_score, 1), "Offer": offer["Player"],
                    "Offer FP/G": round(float(offer["Advice score"]), 1),
                    "Weak-slot gain": round(weak_gain, 1),
                    "Estimated net starter gain": round(net_gain, 1),
                    "Why they may listen": (
                        f"Their weakest position is {their_need}; your offer comes from your {my_strength} surplus."
                        if their_need == my_strength else
                        f"Values are within a realistic range; ask whether they need {my_strength} depth."
                    ),
                    "Trade grade": "Strong fit" if net_gain >= 2 and their_need == my_strength else "Explore",
                })
                break
    trade_frame = pd.DataFrame(trade_moves)
    if not trade_frame.empty:
        trade_frame = trade_frame.sort_values(
            ["Estimated net starter gain", "Weak-slot gain"], ascending=False
        ).drop_duplicates("Target").head(6)
    return weaknesses, waiver_frame, trade_frame, pd.DataFrame(applied_claims), long_term_frame


def draft_recap(league, team_rows, previous_league=None):
    """Grade draft value using current/projection rank versus original pick."""
    player_data = {
        row["Player"]: row
        for rows in team_rows.values() for row in rows
    }
    picks = list(getattr(league, "draft", []) or [])
    pick_ids = [getattr(pick, "playerId", None) for pick in picks if getattr(pick, "playerId", None)]
    details, previous_details = {}, {}
    if pick_ids:
        try:
            found = league.player_info(playerId=pick_ids)
            if not isinstance(found, list):
                found = [found]
            details = {p.playerId: p for p in found if p is not None}
        except Exception:
            pass
        if previous_league is not None:
            try:
                found = previous_league.player_info(playerId=pick_ids)
                if not isinstance(found, list):
                    found = [found]
                previous_details = {p.playerId: p for p in found if p is not None}
            except Exception:
                pass
    scored = []
    for pick in picks:
        player_name = getattr(pick, "playerName", "Unknown")
        row = player_data.get(player_name, {})
        player_id = getattr(pick, "playerId", None)
        detail = details.get(player_id)
        completed_scores = [score for _, score in game_score_records(detail)] if detail is not None else []
        value = statistics.mean(completed_scores) if completed_scores else row.get("Advice score")
        if value is None and detail is not None:
            value = blended_projection(detail, previous_player=previous_details.get(player_id))["blended_fppg"]
        if detail is not None and not row:
            row = {"Injury status": getattr(detail, "injuryStatus", "Unknown")}
        overall_pick = (int(getattr(pick, "round_num", 1)) - 1) * len(league.teams) + int(getattr(pick, "round_pick", 1))
        scored.append({"pick": pick, "Player": player_name, "Overall pick": overall_pick, "Current FP/G": value, "row": row})
    ranked = sorted([item for item in scored if item["Current FP/G"] is not None], key=lambda x: x["Current FP/G"], reverse=True)
    current_rank = {item["Player"]: index + 1 for index, item in enumerate(ranked)}
    output = []
    for item in scored:
        rank = current_rank.get(item["Player"])
        availability_penalty = 2 if str(item["row"].get("Injury status", "")).upper() not in HEALTHY_STATUSES else 0
        if rank is None:
            grade = 3
        else:
            surplus = item["Overall pick"] - rank
            grade = max(1, min(10, round(5.5 + surplus / 12 - availability_penalty)))
        label = "Major steal" if grade >= 9 else "Good value" if grade >= 7 else "Fair value" if grade >= 5 else "Disappointing" if grade >= 3 else "Major miss"
        pick = item["pick"]
        output.append({
            "Drafted by": getattr(getattr(pick, "team", None), "team_name", "Unknown"),
            "Player": item["Player"], "Overall pick": item["Overall pick"],
            "Round": getattr(pick, "round_num", None), "Pick in round": getattr(pick, "round_pick", None),
            "Current FP/G": item["Current FP/G"], "Current value rank": rank,
            "Value score (1–10)": grade, "Assessment": label,
        })
    return pd.DataFrame(output).sort_values("Overall pick") if output else pd.DataFrame()


def boom_bust_board(league, schedule, previous_league=None, waiver_size=20, defense_context=None):
    """Estimate upside/downside from projection, real volatility, role, and availability."""
    rostered = [p for team in league.teams for p in team.roster]
    waiver = list(league.free_agents(size=waiver_size))
    players = rostered + waiver
    details = {}
    try:
        result = league.player_info(playerId=[p.playerId for p in players])
        if not isinstance(result, list):
            result = [result]
        details = {p.playerId: p for p in result if p is not None}
    except Exception:
        pass
    today_games = schedule["games"][schedule["games"]["game_date"] == date.today()]
    opponent = {}
    for _, game in today_games.iterrows():
        home, away = game["homeTeam_teamTricode"], game["awayTeam_teamTricode"]
        opponent[home], opponent[away] = away, home
    injury_pool = injury_pool_from_league(league) + waiver
    defense_context = defense_context or {}
    league_allowed = statistics.mean(defense_context.values()) if defense_context else None
    rows = []
    for player in players:
        detail = details.get(player.playerId, player)
        scores = [score for _, score in game_score_records(detail)]
        projected = None
        for group_key, group in getattr(detail, "stats", {}).items():
            if str(group_key).endswith("_projected") and isinstance(group, Mapping):
                try:
                    projected = float(group.get("applied_avg"))
                except (TypeError, ValueError):
                    pass
        baseline = statistics.mean(scores) if scores else projected
        if baseline is None:
            continue
        volatility = statistics.pstdev(scores) if len(scores) >= 3 else max(6.0, baseline * 0.22)
        recent = statistics.mean(scores[-3:]) if len(scores) >= 3 else baseline
        trend = recent - baseline
        role_flag = opportunity_flag(player, injury_pool)
        role_boost = min(4.0, baseline * 0.07) if role_flag else 0
        center = baseline + 0.35 * trend + role_boost
        boom = center + volatility
        bust = max(0, center - volatility)
        status = str(getattr(player, "injuryStatus", "Unknown"))
        unavailable = is_unavailable_status(status)
        boom_chance = 20 + (8 if trend > 2 else -5 if trend < -2 else 0) + (7 if role_flag else 0) - (12 if unavailable else 0)
        bust_chance = 20 + (10 if trend < -2 else -4 if trend > 2 else 0) + (22 if unavailable else 0)
        boom_chance = max(5, min(55, boom_chance))
        bust_chance = max(5, min(65, bust_chance))
        confidence = "High" if len(scores) >= 10 else "Medium" if len(scores) >= 3 else "Low"
        reasons = []
        if role_flag:
            reasons.append(role_flag)
        if trend > 2:
            reasons.append("recent scoring is above baseline")
        elif trend < -2:
            reasons.append("recent scoring is below baseline")
        if str(status).upper() not in HEALTHY_STATUSES:
            reasons.append(f"ESPN status is {status}")
        nba_team = normalize_nba_team(getattr(player, "proTeam", ""))
        next_opponent = opponent.get(nba_team)
        opponent_allowed = defense_context.get(next_opponent)
        if opponent_allowed is None or league_allowed is None:
            opponent_effect = "Neutral — current-season defensive sample is insufficient" if next_opponent else "No game today"
        elif opponent_allowed >= league_allowed + 2:
            opponent_effect = f"Favorable — {next_opponent} allows {opponent_allowed:.1f} points/game"
            center += min(2.5, baseline * 0.04)
        elif opponent_allowed <= league_allowed - 2:
            opponent_effect = f"Difficult — {next_opponent} allows {opponent_allowed:.1f} points/game"
            center -= min(2.5, baseline * 0.04)
        else:
            opponent_effect = f"Neutral — {next_opponent} is near league average"
        boom, bust = center + volatility, max(0, center - volatility)
        rows.append({
            "Player": player.name, "NBA team": nba_team, "Positions": "/".join(player_positions(player)),
            "Opponent today": opponent.get(nba_team, "No game"), "Projection": round(center, 1),
            "Boom score": round(boom, 1), "Boom differential": round(boom-center, 1),
            "Boom chance": f"{boom_chance}%",
            "Bust score": round(bust, 1), "Bust differential": round(bust-center, 1),
            "Bust chance": f"{bust_chance}%",
            "Volatility": round(volatility, 1), "Minutes last 7": rolling_stat_average(detail, "MIN", 7),
            "FGA last 7": rolling_stat_average(detail, "FGA", 7), "Injury status": status,
            "Opponent effect": opponent_effect,
            "Confidence": confidence, "Why": "; ".join(reasons) or "Projection driven mainly by established baseline and historical variance.",
        })
    return pd.DataFrame(rows).sort_values("Boom differential", ascending=False) if rows else pd.DataFrame()


def matchup_forecasts(league, team, schedules, previous_league=None, team_rows=None):
    """Forecast the user's next matchup periods from legal daily lineups."""
    start_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    rows, details = [], {}
    for offset, schedule in enumerate(schedules):
        period = start_period + offset
        try:
            matchups = league.scoreboard(matchupPeriod=period)
            matchup = next(m for m in matchups if team.team_id in {m.home_team.team_id, m.away_team.team_id})
            opponent = matchup.away_team if matchup.home_team.team_id == team.team_id else matchup.home_team
        except Exception:
            continue
        my_plan = weekly_lineup_plan(
            league, team, schedule, previous_league,
            base_rows=(team_rows or {}).get(team.team_id),
        )
        opp_plan = weekly_lineup_plan(
            league, opponent, schedule, previous_league,
            base_rows=(team_rows or {}).get(opponent.team_id),
        )
        def total(plan):
            return sum(float(r["Advice score"]) for day in plan.values() for r in day if str(r["Recommendation"]).startswith("Start") and r["Advice score"] is not None)
        mine, theirs = total(my_plan), total(opp_plan)
        margin = mine - theirs
        scale = max(45.0, 0.08 * ((mine + theirs) / 2))
        win_probability = 1 / (1 + math.exp(-margin / scale))
        rows.append({
            "Fantasy week": period, "Dates": f"{schedule['start_date']:%b %d}–{schedule['end_date']:%b %d}",
            "Opponent": opponent.team_name, "Your projection": round(mine, 1),
            "Opponent projection": round(theirs, 1), "Projected margin": round(margin, 1),
            "Win probability": f"{win_probability:.0%}", "Favored": team.team_name if margin >= 0 else opponent.team_name,
            "Confidence": "Medium" if offset == 0 else "Low",
        })
        details[period] = {"mine": my_plan, "opponent": opp_plan, "opponent_name": opponent.team_name}
    return pd.DataFrame(rows), details


def remaining_plan_projection(plan, schedule, reference_date=None):
    """Estimate unscored points remaining in a legal daily lineup plan."""
    reference_date = reference_date or date.today()
    games = schedule.get("games", pd.DataFrame())
    status_by_team = {}
    if not games.empty and "game_date" in games.columns:
        today_games = games[games["game_date"] == reference_date]
        for _, game in today_games.iterrows():
            try:
                status = int(game.get("gameStatus", 1) or 1)
            except (TypeError, ValueError):
                status = 1
            # NBA status: 1 scheduled, 2 live, 3 final. A live game gets a
            # conservative half-game remainder because player-level clocks
            # are not available from ESPN's fantasy feed.
            factor = 1.0 if status == 1 else 0.5 if status == 2 else 0.0
            status_by_team[str(game.get("homeTeam_teamTricode", ""))] = factor
            status_by_team[str(game.get("awayTeam_teamTricode", ""))] = factor
    total, starts = 0.0, 0.0
    for day, rows in plan.items():
        if day < reference_date:
            continue
        for row in rows:
            if not str(row.get("Recommendation", "")).startswith("Start"):
                continue
            score = row.get("Advice score")
            if score is None:
                continue
            factor = 1.0 if day > reference_date else status_by_team.get(
                str(row.get("NBA team", "")), 1.0
            )
            if factor > 0:
                total += float(score) * factor
                starts += factor
    return round(total, 1), round(starts, 1)


def live_matchup_outlook(my_live, opponent_live, my_remaining,
                         opponent_remaining, my_remaining_games=0,
                         opponent_remaining_games=0):
    """Convert live scores and unplayed legal starts into an explainable probability."""
    my_live = float(my_live or 0)
    opponent_live = float(opponent_live or 0)
    my_remaining = float(my_remaining or 0)
    opponent_remaining = float(opponent_remaining or 0)
    my_final = my_live + my_remaining
    opponent_final = opponent_live + opponent_remaining
    margin = my_final - opponent_final
    uncertainty = max(28.0, 0.085 * (my_remaining + opponent_remaining))
    probability = 1 / (1 + math.exp(-margin / uncertainty))
    remaining_share = (my_remaining + opponent_remaining) / max(
        1.0, my_final + opponent_final
    )
    confidence = (
        "Low" if remaining_share > 0.60
        else "Medium" if remaining_share > 0.25
        else "High"
    )
    swing = opponent_final - my_final
    if probability >= 0.72:
        summary = "You are in control, but unfinished games still matter."
    elif probability >= 0.55:
        summary = "You have a narrow edge; lineup execution can decide it."
    elif probability >= 0.45:
        summary = "The matchup is effectively a toss-up."
    elif probability >= 0.28:
        summary = "You are slightly behind and need your remaining games to outperform."
    else:
        summary = "You need a meaningful upside outcome from the remaining schedule."
    return {
        "win_probability": round(probability * 100),
        "my_projected_final": round(my_final, 1),
        "opponent_projected_final": round(opponent_final, 1),
        "projected_margin": round(margin, 1),
        "confidence": confidence,
        "summary": summary,
        "my_remaining": round(my_remaining, 1),
        "opponent_remaining": round(opponent_remaining, 1),
        "my_remaining_games": my_remaining_games,
        "opponent_remaining_games": opponent_remaining_games,
        "points_needed": round(max(0.0, swing), 1),
    }


def roster_value_board(roster_rows, waivers):
    """Measure roster value above the best healthy waiver replacement by position."""
    positions = ["PG", "SG", "SF", "PF", "C"]
    replacement = {position: None for position in positions}
    replacement_name = {position: None for position in positions}
    if not waivers.empty:
        for _, waiver in waivers.iterrows():
            rating = waiver.get("Weighted rating")
            if pd.isna(rating):
                rating = waiver.get("Projected FP/G")
            if pd.isna(rating) or is_unavailable_status(waiver.get("Injury status")):
                continue
            eligible = str(waiver.get("Positions", "")).upper().split("/")
            for position in positions:
                if position in eligible and (
                    replacement[position] is None
                    or float(rating) > replacement[position]
                ):
                    replacement[position] = float(rating)
                    replacement_name[position] = str(waiver.get("Player", "Unknown"))
    rows = []
    for player in roster_rows:
        score = player.get("Advice score")
        eligible = [p for p in player.get("Eligible", []) if p in positions]
        available_levels = [
            (replacement[p], p) for p in eligible if replacement[p] is not None
        ]
        # Use the strongest freely available alternative that could replace
        # this roster spot. This is deliberately conservative.
        level, comparison_position = (
            max(available_levels) if available_levels else (None, None)
        )
        vorp = None if score is None or level is None else round(float(score) - level, 1)
        if vorp is None:
            tier, action = "Uncertain", "Get more data"
        elif vorp >= 10:
            tier, action = "Foundation", "Hold"
        elif vorp >= 5:
            tier, action = "Strong starter", "Hold"
        elif vorp >= 1.5:
            tier, action = "Useful depth", "Keep, but compare offers"
        elif vorp >= 0:
            tier, action = "Marginal edge", "Upgradeable"
        else:
            tier, action = "Below replacement", "Waiver/drop candidate"
        rows.append({
            "Player": player.get("Player"),
            "Positions": player.get("Positions") or "/".join(eligible),
            "Injury status": player.get("Injury status", "Unknown"),
            "Player rating": None if score is None else round(float(score), 1),
            "Replacement FP/G": None if level is None else round(level, 1),
            "VORP": vorp,
            "Value tier": tier,
            "Recommended treatment": action,
            "Compared at": comparison_position or "Unknown",
            "Best available comparison": (
                replacement_name.get(comparison_position) if comparison_position else None
            ),
        })
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(
            ["VORP", "Player rating"], ascending=[False, False], na_position="last"
        ).reset_index(drop=True)
    replacement_frame = pd.DataFrame([
        {
            "Position": position,
            "Replacement player": replacement_name[position] or "Unavailable",
            "Replacement FP/G": (
                None if replacement[position] is None
                else round(replacement[position], 1)
            ),
        }
        for position in positions
    ])
    return frame, replacement_frame


def playoff_schedule_grades(schedules):
    """Grade NBA schedules across two two-week fantasy playoff rounds."""
    if len(schedules) < 4:
        return pd.DataFrame()
    counts = defaultdict(lambda: [0, 0, 0, 0])
    for week_index, schedule in enumerate(schedules[:4]):
        for _, row in schedule["game_counts"].iterrows():
            counts[str(row["NBA team"])][week_index] = int(row["Games"])
    rows = []
    for team, weeks in counts.items():
        round_one = sum(weeks[:2])
        championship = sum(weeks[2:4])
        total = round_one + championship
        rows.append({
            "NBA team": team,
            "Round 1 games": round_one,
            "Championship games": championship,
            "Total playoff games": total,
            "Championship weight": round(0.45 * round_one + 0.55 * championship, 2),
            "Weekly pattern": "–".join(str(value) for value in weeks),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    maximum = float(frame["Championship weight"].max())
    minimum = float(frame["Championship weight"].min())
    span = max(1.0, maximum - minimum)
    frame["Schedule grade"] = frame["Championship weight"].map(
        lambda value: round(100 * (float(value) - minimum) / span)
    )
    frame["Schedule tier"] = frame["Schedule grade"].map(
        lambda grade: (
            "Elite" if grade >= 80 else "Good" if grade >= 60
            else "Neutral" if grade >= 35 else "Difficult"
        )
    )
    return frame.sort_values(
        ["Championship weight", "Total playoff games"], ascending=False
    ).reset_index(drop=True)


def playoff_player_values(roster_rows, waivers, schedule_grades):
    """Attach playoff volume and projected totals to roster and waiver players."""
    if schedule_grades.empty:
        return pd.DataFrame(), pd.DataFrame()
    schedule_map = schedule_grades.set_index("NBA team").to_dict("index")

    def build(rows, source):
        output = []
        iterable = rows.iterrows() if isinstance(rows, pd.DataFrame) else enumerate(rows)
        for _, row in iterable:
            nba_team = str(row.get("NBA team", ""))
            schedule = schedule_map.get(nba_team)
            if not schedule:
                continue
            rating = row.get("Advice score") if source == "Roster" else row.get("Weighted rating")
            if pd.isna(rating):
                rating = row.get("Projected FP/G")
            if pd.isna(rating):
                continue
            output.append({
                "Player": row.get("Player"), "Source": source,
                "NBA team": nba_team,
                "Positions": row.get("Positions", "Unknown"),
                "Injury status": row.get("Injury status", "Unknown"),
                "FP/G rating": round(float(rating), 1),
                "Round 1 games": schedule["Round 1 games"],
                "Championship games": schedule["Championship games"],
                "Total playoff games": schedule["Total playoff games"],
                "Schedule tier": schedule["Schedule tier"],
                "Projected playoff points": round(
                    float(rating) * schedule["Total playoff games"], 1
                ),
            })
        return pd.DataFrame(output)

    roster = build(roster_rows, "Roster")
    waiver = build(waivers, "Waiver")
    if not roster.empty:
        roster = roster.sort_values("Projected playoff points", ascending=False).reset_index(drop=True)
    if not waiver.empty:
        waiver = waiver[
            ~waiver["Injury status"].apply(is_unavailable_status)
        ].sort_values("Projected playoff points", ascending=False).reset_index(drop=True)
    return roster, waiver


def transaction_portfolio(ranked_moves, pending_claims=None):
    """Build a primary waiver plan, same-drop fallback, and independent pivot."""
    columns = [
        "Priority", "Role", "Add", "Drop", "Week 1 gain", "2-week gain",
        "4-week gain", "Trigger",
    ]
    if ranked_moves is None or ranked_moves.empty:
        return pd.DataFrame(columns=columns)
    candidates = ranked_moves[ranked_moves["2-week gain"] > 0].copy()
    if candidates.empty:
        return pd.DataFrame(columns=columns)
    candidates = candidates.sort_values(
        ["2-week gain", "4-week gain", "Week 1 gain"], ascending=False
    )
    selected = []
    primary = candidates.iloc[0]
    selected.append(("Primary", primary, "Use if the player remains available."))
    fallback_pool = candidates[
        (candidates["Add"] != primary["Add"])
        & (candidates["Drop"] == primary["Drop"])
    ]
    if not fallback_pool.empty:
        selected.append((
            "Fallback", fallback_pool.iloc[0],
            f"Use only if {primary['Add']} is unavailable or the first claim fails.",
        ))
    used_adds = {str(row[1]["Add"]) for row in selected}
    pivot_pool = candidates[
        (~candidates["Add"].astype(str).isin(used_adds))
        & (candidates["Drop"] != primary["Drop"])
    ]
    if not pivot_pool.empty:
        selected.append((
            "Independent pivot", pivot_pool.iloc[0],
            "Consider after the primary roster problem is addressed; this targets a different drop spot.",
        ))
    rows = []
    for priority, (role, move, trigger) in enumerate(selected, 1):
        rows.append({
            "Priority": priority, "Role": role, "Add": move["Add"],
            "Drop": move["Drop"], "Week 1 gain": move["Week 1 gain"],
            "2-week gain": move["2-week gain"],
            "4-week gain": move["4-week gain"], "Trigger": trigger,
        })
    return pd.DataFrame(rows, columns=columns)


def injury_contingency_plans(roster_rows, waiver_rows, teams_playing=None):
    """Create read-only if/then plans for every roster injury designation."""
    teams_playing = set(teams_playing or [])
    healthy_roster = [
        row for row in roster_rows
        if str(row.get("Injury status", "")).upper() in HEALTHY_STATUSES
    ]
    plans = []
    for injured in roster_rows:
        status = str(injured.get("Injury status", "Unknown") or "Unknown").upper()
        if status in HEALTHY_STATUSES:
            continue
        positions = set(injured.get("Eligible", []))
        roster_options = [
            row for row in healthy_roster
            if row.get("Player") != injured.get("Player")
            and positions.intersection(row.get("Eligible", []))
            and bool(row.get("Game today"))
            and not str(row.get("Recommendation", "")).startswith("Start")
        ]
        roster_options.sort(
            key=lambda row: row.get("Advice score")
            if row.get("Advice score") is not None else -1,
            reverse=True,
        )
        waiver_options = []
        if waiver_rows is not None and not waiver_rows.empty:
            for _, waiver in waiver_rows.iterrows():
                waiver_positions = set(
                    str(waiver.get("Positions", "")).upper().split("/")
                )
                rating = waiver.get("Weighted rating")
                if pd.isna(rating):
                    rating = waiver.get("Projected FP/G")
                if (
                    positions.intersection(waiver_positions)
                    and str(waiver.get("NBA team", "")) in teams_playing
                    and not is_unavailable_status(waiver.get("Injury status"))
                    and not pd.isna(rating)
                ):
                    waiver_options.append((float(rating), waiver))
        waiver_options.sort(key=lambda item: item[0], reverse=True)
        roster_replacement = roster_options[0] if roster_options else None
        waiver_replacement = waiver_options[0][1] if waiver_options else None
        if status in INACTIVE_STATUSES or status.startswith("OUT"):
            trigger = "Act now unless ESPN changes the player to active before lineup lock."
            action = "Move to IR/bench if eligible and use the best legal replacement."
        else:
            trigger = "Activate this plan only if the player is ruled out or receives a firm minutes restriction."
            action = "Keep the player for now and recheck near tipoff."
        plans.append({
            "Player": injured.get("Player"), "Status": status,
            "Positions": injured.get("Positions", "/".join(positions)),
            "Trigger": trigger, "Immediate action": action,
            "Roster replacement": (
                roster_replacement.get("Player") if roster_replacement else "No healthy bench fit playing today"
            ),
            "Roster replacement FP/G": (
                roster_replacement.get("Advice score") if roster_replacement else None
            ),
            "Waiver fallback": (
                waiver_replacement.get("Player") if waiver_replacement is not None
                else "No healthy positional waiver fit playing today"
            ),
            "Waiver fallback FP/G": (
                waiver_options[0][0] if waiver_options else None
            ),
        })
    return pd.DataFrame(plans)


def matchup_counterstrategy(my_plan, opponent_plan):
    """Summarize daily lineup leverage and the opponent's largest point threats."""
    days = sorted(set(my_plan) | set(opponent_plan))
    daily = []
    opponent_totals = defaultdict(lambda: {"points": 0.0, "games": 0, "team": ""})

    def starters(rows):
        return [
            row for row in rows
            if str(row.get("Recommendation", "")).startswith("Start")
            and row.get("Advice score") is not None
        ]

    for day in days:
        mine = starters(my_plan.get(day, []))
        theirs = starters(opponent_plan.get(day, []))
        my_points = sum(float(row["Advice score"]) for row in mine)
        their_points = sum(float(row["Advice score"]) for row in theirs)
        margin = my_points - their_points
        daily.append({
            "Date": day, "Your starters": len(mine),
            "Opponent starters": len(theirs),
            "Your projected points": round(my_points, 1),
            "Opponent projected points": round(their_points, 1),
            "Daily edge": round(margin, 1),
            "Leverage": (
                "Attack" if margin >= 20 else "Protect" if margin <= -20
                else "Close"
            ),
        })
        for row in theirs:
            item = opponent_totals[str(row.get("Player"))]
            item["points"] += float(row["Advice score"])
            item["games"] += 1
            item["team"] = row.get("NBA team", "Unknown")
    threats = pd.DataFrame([
        {
            "Player": player, "NBA team": values["team"],
            "Usable games": values["games"],
            "Projected matchup points": round(values["points"], 1),
        }
        for player, values in opponent_totals.items()
    ])
    if not threats.empty:
        threats = threats.sort_values(
            "Projected matchup points", ascending=False
        ).reset_index(drop=True)
    return pd.DataFrame(daily), threats


def projection_accuracy_lab(saved_forecasts, saved_results):
    """Join immutable forecasts to archived results and diagnose model error."""
    results_by_period = {
        int(row["matchup_period"]): row for row in (saved_results or [])
    }
    rows = []
    for forecast in saved_forecasts or []:
        period = int(forecast["matchup_period"])
        actual = results_by_period.get(period)
        if actual is None:
            continue
        projected_me = float(forecast["team_projection"])
        projected_opponent = float(forecast["opponent_projection"])
        actual_me = float(actual["team_score"])
        actual_opponent = float(actual["opponent_score"])
        projected_margin = projected_me - projected_opponent
        actual_margin = actual_me - actual_opponent
        scale = max(45.0, 0.08 * ((projected_me + projected_opponent) / 2))
        probability = 1 / (1 + math.exp(-projected_margin / scale))
        outcome = 1.0 if actual_margin > 0 else 0.0 if actual_margin < 0 else 0.5
        rows.append({
            "Week": period, "Opponent": actual["opponent"],
            "Projected score": projected_me, "Actual score": actual_me,
            "Score error": round(actual_me - projected_me, 1),
            "Absolute score error": round(abs(actual_me - projected_me), 1),
            "Projected opponent": projected_opponent,
            "Actual opponent": actual_opponent,
            "Projected margin": round(projected_margin, 1),
            "Actual margin": round(actual_margin, 1),
            "Margin error": round(actual_margin - projected_margin, 1),
            "Win probability": round(probability * 100),
            "Winner correct": (
                "Yes" if (projected_margin >= 0) == (actual_margin >= 0) else "No"
            ),
            "Brier score": round((probability - outcome) ** 2, 3),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {
            "weeks": 0, "score_mae": None, "margin_mae": None,
            "bias": None, "winner_accuracy": None, "brier": None,
            "confidence": "No completed sample", "diagnosis": "Waiting for a completed saved forecast.",
        }
    frame = frame.sort_values("Week").reset_index(drop=True)
    weeks = len(frame)
    bias = round(float(frame["Score error"].mean()), 1)
    if bias >= 12:
        diagnosis = f"The model is projecting your team too low by about {abs(bias):.1f} points per matchup."
    elif bias <= -12:
        diagnosis = f"The model is projecting your team too high by about {abs(bias):.1f} points per matchup."
    else:
        diagnosis = "The model's average team-score bias is currently close to neutral."
    confidence = (
        "Early sample" if weeks < 3 else "Developing" if weeks < 6
        else "Useful" if weeks < 10 else "Established"
    )
    return frame, {
        "weeks": weeks,
        "score_mae": round(float(frame["Absolute score error"].mean()), 1),
        "margin_mae": round(float(frame["Margin error"].abs().mean()), 1),
        "bias": bias,
        "winner_accuracy": round(float((frame["Winner correct"] == "Yes").mean()) * 100),
        "brier": round(float(frame["Brier score"].mean()), 3),
        "confidence": confidence,
        "diagnosis": diagnosis,
    }


def weekly_team_recap(matchups, prior_scores=None):
    """Rank every fantasy team for one completed period and explain the result."""
    prior_scores = prior_scores or {}
    raw = []
    for matchup in matchups:
        home_score = _match_score(matchup, "home")
        away_score = _match_score(matchup, "away")
        if home_score is None or away_score is None:
            continue
        for team, opponent, score, opponent_score in [
            (matchup.home_team, matchup.away_team, home_score, away_score),
            (matchup.away_team, matchup.home_team, away_score, home_score),
        ]:
            raw.append({
                "Team": team.team_name, "Opponent": opponent.team_name,
                "Score": float(score), "Opponent score": float(opponent_score),
                "Margin": float(score) - float(opponent_score),
            })
    if not raw:
        return pd.DataFrame()
    frame = pd.DataFrame(raw).sort_values("Score", ascending=False).reset_index(drop=True)
    frame["Weekly scoring rank"] = range(1, len(frame) + 1)
    league_average = float(frame["Score"].mean())
    interpretations, trends = [], []
    for _, row in frame.iterrows():
        history = prior_scores.get(row["Team"], [])
        prior_average = statistics.mean(history) if history else None
        trend = None if prior_average is None else float(row["Score"]) - prior_average
        trends.append(None if trend is None else round(trend, 1))
        result = "Win" if row["Margin"] > 0 else "Loss" if row["Margin"] < 0 else "Tie"
        if row["Margin"] >= 75 and row["Score"] >= league_average:
            interpretation = "Dominant win — high output and a decisive margin."
        elif row["Margin"] > 0 and row["Score"] < league_average:
            interpretation = "Efficient win — below-average scoring, but enough to beat this opponent."
        elif row["Margin"] > 0:
            interpretation = "Strong win — above-average scoring converted into a result."
        elif row["Margin"] < 0 and row["Score"] >= league_average:
            interpretation = "Unlucky loss — strong scoring ran into an even better opponent."
        elif row["Margin"] <= -75:
            interpretation = "Concerning loss — both the scoring level and margin need attention."
        elif row["Margin"] < 0:
            interpretation = "Competitive loss — improvement is needed, but the matchup remained reachable."
        else:
            interpretation = "Even matchup — neither side created separation."
        if trend is not None:
            interpretation += (
                f" Output rose {abs(trend):.1f} versus its prior average."
                if trend >= 0 else
                f" Output fell {abs(trend):.1f} versus its prior average."
            )
        interpretations.append(interpretation)
    frame["Result"] = frame["Margin"].map(
        lambda value: "W" if value > 0 else "L" if value < 0 else "T"
    )
    frame["Vs league average"] = (frame["Score"] - league_average).round(1)
    frame["Vs prior average"] = trends
    frame["Interpretation"] = interpretations
    return frame[[
        "Weekly scoring rank", "Team", "Result", "Score", "Opponent",
        "Opponent score", "Margin", "Vs league average", "Vs prior average",
        "Interpretation",
    ]]


def weekly_player_recap(players, start_date, end_date):
    """Rank rostered players by custom points produced inside one date window."""
    rows = []
    seen = set()
    for player in players:
        player_id = getattr(player, "playerId", None)
        identity = player_id if player_id is not None else getattr(player, "name", None)
        if identity in seen:
            continue
        seen.add(identity)
        scores = [
            score for game_date, score in game_score_records(player)
            if start_date <= game_date <= end_date
        ]
        if not scores:
            continue
        rows.append({
            "Player": getattr(player, "name", "Unknown"),
            "NBA team": normalize_nba_team(getattr(player, "proTeam", "")),
            "Games": len(scores), "Total custom FP": round(sum(scores), 1),
            "Custom FP/G": round(sum(scores) / len(scores), 1),
            "Best game": round(max(scores), 1),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.sort_values("Total custom FP", ascending=False).reset_index(drop=True)
    frame["Performance tier"] = [
        "Week winner" if index < max(1, len(frame) // 10)
        else "Strong" if index < max(3, len(frame) // 3)
        else "Steady" if index < max(5, 2 * len(frame) // 3)
        else "Quiet"
        for index in range(len(frame))
    ]
    return frame


def projection_accuracy(league, team, saved_forecasts):
    """Compare preserved pre-week forecasts with completed ESPN results."""
    current = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    rows = []
    for forecast in saved_forecasts:
        period = int(forecast["matchup_period"])
        if period >= current:
            continue
        try:
            matchup = next(
                m for m in league.scoreboard(matchupPeriod=period)
                if team.team_id in {m.home_team.team_id, m.away_team.team_id}
            )
        except Exception:
            continue
        is_home = matchup.home_team.team_id == team.team_id
        actual_me = _match_score(matchup, "home" if is_home else "away")
        actual_opp = _match_score(matchup, "away" if is_home else "home")
        if actual_me is None or actual_opp is None:
            continue
        projected_me = float(forecast["team_projection"])
        projected_opp = float(forecast["opponent_projection"])
        winner_correct = (projected_me >= projected_opp) == (actual_me >= actual_opp)
        rows.append({
            "Week": period, "Opponent": forecast["opponent"],
            "Projected": projected_me, "Actual": actual_me,
            "Error": round(actual_me - projected_me, 1),
            "Absolute error": round(abs(actual_me - projected_me), 1),
            "Winner correct": "Yes" if winner_correct else "No",
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {"weeks": 0, "mae": None, "winner_accuracy": None, "bias": None}
    return frame, {
        "weeks": len(frame), "mae": round(float(frame["Absolute error"].mean()), 1),
        "winner_accuracy": round(float((frame["Winner correct"] == "Yes").mean()) * 100),
        "bias": round(float(frame["Error"].mean()), 1),
    }
