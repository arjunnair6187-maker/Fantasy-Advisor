"""Read-only adapter for the public Sleeper NFL league API."""

from dataclasses import dataclass, field
from types import SimpleNamespace

import requests
import streamlit as st


API_ROOT = "https://api.sleeper.app/v1"
PLAYER_POSITIONS = {"DEF": "D/ST", "DST": "D/ST"}


class SleeperAPIError(RuntimeError):
    """Raised when Sleeper returns an invalid or unavailable response."""


def _get_json(path, *, params=None):
    try:
        response = requests.get(f"{API_ROOT}/{path.lstrip('/')}", params=params, timeout=20)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as error:
        raise SleeperAPIError("Sleeper could not return the requested league data.") from error


def find_user_leagues(username, season):
    username = str(username or "").strip()
    if not username:
        raise ValueError("Enter your Sleeper username.")
    user = _get_json(f"user/{requests.utils.quote(username, safe='')}")
    if not isinstance(user, dict) or not user.get("user_id"):
        raise LookupError("Sleeper did not find that username.")
    leagues = _get_json(f"user/{user['user_id']}/leagues/nfl/{int(season)}") or []
    if not isinstance(leagues, list):
        raise SleeperAPIError("Sleeper returned an unexpected league list.")
    return user, [league for league in leagues if isinstance(league, dict)]


@st.cache_data(ttl=86400, show_spinner=False)
def _players_by_id(sport="nfl"):
    """Sleeper recommends refreshing this large, public player map at most daily."""
    value = _get_json(f"players/{sport}")
    if not isinstance(value, dict):
        raise SleeperAPIError("Sleeper returned an unexpected player directory.")
    return value


@st.cache_data(ttl=3600, show_spinner=False)
def _trending_adds(sport="nfl", lookback_hours=168, limit=100):
    value = _get_json(
        f"players/{sport}/trending/add",
        params={"lookback_hours": int(lookback_hours), "limit": int(limit)},
    )
    return value if isinstance(value, list) else []


def _position(value):
    position = str(value or "Unknown").upper()
    return PLAYER_POSITIONS.get(position, position)


@dataclass
class SleeperPlayer:
    playerId: str
    name: str
    position: str
    proTeam: str
    lineupSlot: str = "BE"
    eligibleSlots: list[str] = field(default_factory=list)
    injuryStatus: str = "Active"
    stats: dict = field(default_factory=dict)
    total_points: float | None = None
    avg_points: float | None = None
    projected_total_points: float | None = None
    projected_avg_points: float | None = None
    percent_owned: float | None = None
    trending_adds: int = 0
    schedule: dict = field(default_factory=dict)


@dataclass
class SleeperTeam:
    team_id: int
    team_name: str
    roster: list[SleeperPlayer]
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0


class SleeperLeague:
    """Expose the read-only NFL fields used by Fantasy Advisor's NFL HUD."""

    provider = "sleeper"

    def __init__(self, league_id, year, *, username="", user_id=""):
        self.league_id = str(league_id)
        self.year = int(year)
        self.username = str(username or "")
        self.user_id = str(user_id or "")
        self._league_data = _get_json(f"league/{self.league_id}")
        if not isinstance(self._league_data, dict):
            raise SleeperAPIError("Sleeper did not return that league.")
        if str(self._league_data.get("sport", "")).lower() != "nfl":
            raise ValueError("Sleeper's documented league-list endpoint currently supports NFL leagues only.")
        if str(self._league_data.get("season", "")) != str(self.year):
            raise ValueError("That Sleeper league does not match the selected season.")

        self.sport = "nfl"
        self.settings = SimpleNamespace(
            reg_season_count=self._regular_season_end(),
            playoff_matchup_period_length=1,
            scoring_format=self._scoring_rows(),
            roster_positions=list(self._league_data.get("roster_positions") or []),
        )
        self.current_week = self._current_week()
        self.nfl_week = self.current_week
        self.rosters = _get_json(f"league/{self.league_id}/rosters") or []
        self.users = _get_json(f"league/{self.league_id}/users") or []
        self._matchup_cache = {}
        self._matchup_cache[self.current_week] = _get_json(
            f"league/{self.league_id}/matchups/{self.current_week}"
        ) or []
        self._player_directory = _players_by_id("nfl")
        self._user_names = self._build_user_names()
        self._team_by_roster_id = {}
        self.teams = self._build_teams()
        self.team_id = None
        self.draft = self._draft_picks()

    def _current_week(self):
        try:
            state = _get_json("state/nfl")
            state_season = str(state.get("season") or "")
            if state_season == str(self.year):
                return max(1, int(state.get("week") or 1))
        except (SleeperAPIError, TypeError, ValueError, AttributeError):
            pass
        return max(1, int(self._league_data.get("settings", {}).get("leg", 1) or 1))

    def _regular_season_end(self):
        settings = self._league_data.get("settings") or {}
        try:
            return max(1, int(settings.get("playoff_week_start") or 15) - 1)
        except (TypeError, ValueError):
            return 14

    def _scoring_rows(self):
        values = self._league_data.get("scoring_settings") or {}
        return [{"stat": name, "points": points} for name, points in values.items()]

    def _build_user_names(self):
        names = {}
        for user in self.users:
            if not isinstance(user, dict):
                continue
            user_id = str(user.get("user_id", ""))
            metadata = user.get("metadata") or {}
            names[user_id] = str(
                metadata.get("team_name") or user.get("display_name") or "Sleeper team"
            )
        return names

    def _build_teams(self):
        teams = []
        for roster in self.rosters:
            if not isinstance(roster, dict):
                continue
            roster_id = int(roster.get("roster_id", 0))
            settings = roster.get("settings") or {}
            starter_ids = {str(player_id) for player_id in roster.get("starters") or []}
            player_scores = self._current_player_scores(roster_id)
            players = []
            for player_id in roster.get("players") or []:
                key = str(player_id)
                raw = self._player_directory.get(key) or {}
                position = _position(raw.get("position"))
                points = player_scores.get(key)
                players.append(SleeperPlayer(
                    playerId=key,
                    name=self._player_name(raw, key),
                    position=position,
                    proTeam=str(raw.get("team") or "—"),
                    lineupSlot=(position if key in starter_ids else "BE"),
                    eligibleSlots=[_position(item) for item in raw.get("fantasy_positions") or [position]],
                    injuryStatus=str(raw.get("injury_status") or "Active"),
                    stats={self.current_week: {"points": points}} if points is not None else {},
                    total_points=None,
                    avg_points=None,
                    percent_owned=None,
                ))
            owner_id = str(roster.get("owner_id") or "")
            team = SleeperTeam(
                team_id=roster_id,
                team_name=self._user_names.get(owner_id, f"Sleeper team {roster_id}"),
                roster=players,
                wins=int(settings.get("wins", 0) or 0),
                losses=int(settings.get("losses", 0) or 0),
                ties=int(settings.get("ties", 0) or 0),
                points_for=self._as_points(settings.get("fpts"), settings.get("fpts_decimal")),
            )
            teams.append(team)
            self._team_by_roster_id[roster_id] = team
        return teams

    @staticmethod
    def _as_points(whole, decimal):
        try:
            return float(whole or 0) + float(decimal or 0) / 100
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _player_name(player, fallback):
        first = str(player.get("first_name") or "").strip()
        last = str(player.get("last_name") or "").strip()
        full = str(player.get("full_name") or f"{first} {last}".strip())
        return full or f"Player {fallback}"

    def _current_player_scores(self, roster_id):
        rows = self._matchup_cache.get(self.current_week, [])
        for matchup in rows:
            if int(matchup.get("roster_id", -1)) == int(roster_id):
                scores = matchup.get("players_points") or {}
                return {str(key): value for key, value in scores.items()}
        return {}

    def _draft_picks(self):
        try:
            drafts = _get_json(f"league/{self.league_id}/drafts") or []
            draft_ids = [item.get("draft_id") for item in drafts if item.get("draft_id")]
            if not draft_ids:
                return []
            picks = _get_json(f"draft/{draft_ids[0]}/picks") or []
        except (SleeperAPIError, AttributeError):
            return []
        rows = []
        for pick in picks:
            player_id = str(pick.get("player_id") or "")
            player = self._player_directory.get(player_id) or {}
            roster_id = int(pick.get("roster_id") or 0)
            drafted_team = self._team_by_roster_id.get(roster_id)
            rows.append(SimpleNamespace(
                round_num=pick.get("round"),
                round_pick=pick.get("pick_no"),
                player=SimpleNamespace(
                    name=self._player_name(player, player_id),
                    position=_position(player.get("position")),
                    proTeam=player.get("team") or "—",
                ),
                team=drafted_team,
            ))
        return rows

    def _matchups(self, week):
        week = int(week)
        if week not in self._matchup_cache:
            self._matchup_cache[week] = _get_json(
                f"league/{self.league_id}/matchups/{week}"
            ) or []
        data = self._matchup_cache[week]
        grouped = {}
        for row in data:
            key = row.get("matchup_id")
            if key is None:
                continue
            grouped.setdefault(key, []).append(row)
        result = []
        for teams in grouped.values():
            if len(teams) < 2:
                continue
            home, away = teams[:2]
            home_id, away_id = int(home.get("roster_id", 0)), int(away.get("roster_id", 0))
            home_team = self._team_by_roster_id.get(home_id)
            away_team = self._team_by_roster_id.get(away_id)
            if home_team is None or away_team is None:
                continue
            result.append(SimpleNamespace(
                home_team=home_team,
                away_team=away_team,
                home_score=home.get("points"),
                away_score=away.get("points"),
                home_projected=None,
                away_projected=None,
                matchup_id=teams[0].get("matchup_id"),
            ))
        return result

    def box_scores(self, week=None, **_kwargs):
        return self._matchups(week or self.current_week)

    def scoreboard(self, week=None):
        return self._matchups(week or self.current_week)

    def power_rankings(self, week=None):
        return sorted(
            ((team.points_for, team) for team in self.teams),
            key=lambda item: item[0], reverse=True,
        )

    def free_agents(self, week=None, size=50, position=None):
        rostered = {
            str(player.playerId)
            for team in self.teams
            for player in team.roster
        }
        adds = _trending_adds("nfl", 168, max(int(size) * 3, 100))
        league_team_count = max(1, len(self.teams))
        rows = []
        for item in adds:
            player_id = str(item.get("player_id") or "")
            if not player_id or player_id in rostered:
                continue
            raw = self._player_directory.get(player_id) or {}
            player_position = _position(raw.get("position"))
            if position and position not in {"All", player_position}:
                continue
            player = SleeperPlayer(
                playerId=player_id,
                name=self._player_name(raw, player_id),
                position=player_position,
                proTeam=str(raw.get("team") or "—"),
                eligibleSlots=[_position(value) for value in raw.get("fantasy_positions") or [player_position]],
                injuryStatus=str(raw.get("injury_status") or "Active"),
                percent_owned=0.0,
                trending_adds=int(item.get("count") or 0),
            )
            rows.append(player)
            if len(rows) >= int(size):
                break
        return rows

    def waiver_activity(self, team_id):
        """Sleeper exposes processed transactions, not ESPN-style pending claims."""
        own_id = int(team_id)
        recent_rows = []
        for week in range(max(1, self.current_week - 3), self.current_week + 1):
            try:
                transactions = _get_json(f"league/{self.league_id}/transactions/{week}") or []
            except SleeperAPIError:
                continue
            for transaction in transactions:
                roster_ids = {int(value) for value in transaction.get("roster_ids") or []}
                if own_id not in roster_ids:
                    continue
                adds = transaction.get("adds") or {}
                drops = transaction.get("drops") or {}
                recent_rows.append({
                    "Status": str(transaction.get("status") or "complete").title(),
                    "Move type": str(transaction.get("type") or "transaction").replace("_", " ").title(),
                    "Add": ", ".join(self._player_name(self._player_directory.get(str(pid), {}), pid) for pid in adds) or "—",
                    "Drop": ", ".join(self._player_name(self._player_directory.get(str(pid), {}), pid) for pid in drops) or "—",
                    "Claim priority": "—",
                    "Bid": transaction.get("settings", {}).get("waiver_bid") or "—",
                    "Processes": transaction.get("created") or "Not supplied by Sleeper",
                })
        recent_rows.sort(key=lambda row: str(row.get("Processes", "")), reverse=True)
        return [], recent_rows[:20]


def connect_to_sleeper_league(year, league_id, credentials=None):
    credentials = credentials or {}
    return SleeperLeague(
        league_id,
        year,
        username=credentials.get("username", ""),
        user_id=credentials.get("user_id", ""),
    )
