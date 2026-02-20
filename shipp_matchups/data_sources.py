"""
Unified data fetching for Matchup Analyzer.

Aggregates data from multiple external APIs:
  - balldontlie.io — NBA team/player stats (no key)
  - statsapi.mlb.com — MLB team stats, pitcher/batter matchups (no key)
  - football-data.org — Soccer standings, head-to-head (free key)

Each source module exposes a consistent interface for the analyzer to consume.
All functions return dicts/lists; empty results on failure rather than exceptions.
"""

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ===========================================================================
# Rate-Limit Helpers
# ===========================================================================

class RateLimiter:
    """Simple rate limiter that enforces minimum delay between requests."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self.last_request = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()


_bdl_limiter = RateLimiter(2.1)       # 30 req/min
_mlb_limiter = RateLimiter(0.5)       # be courteous
_fbd_limiter = RateLimiter(6.0)       # 10 req/min free tier


def _safe_request(
    method: str,
    url: str,
    limiter: RateLimiter,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 10,
) -> Optional[dict]:
    """Make a rate-limited HTTP request with error handling."""
    limiter.wait()
    try:
        resp = requests.request(
            method, url,
            headers=headers or {},
            params=params or {},
            timeout=timeout,
        )
        if resp.status_code == 429:
            logger.warning("Rate limited by %s. Backing off.", url)
            time.sleep(30)
            return None
        if resp.status_code != 200:
            logger.warning("%s returned %d: %s", url, resp.status_code, resp.text[:200])
            return None
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Request to %s failed: %s", url, exc)
        return None


# ===========================================================================
# balldontlie.io — NBA
# ===========================================================================

BDL_BASE = "https://api.balldontlie.io/v1"


def get_nba_team_stats(team_name: str, season: int = 2025) -> dict:
    """
    Get aggregated team stats for an NBA team.

    Since balldontlie doesn't have a direct team-stats endpoint,
    we fetch recent games and compute averages.

    Returns dict with: ppg, opp_ppg, fg_pct, fg3_pct, reb, ast, tov, record.
    """
    # First, find the team
    data = _safe_request(
        "GET", f"{BDL_BASE}/teams",
        limiter=_bdl_limiter,
    )
    if not data or not data.get("data"):
        return {}

    team = None
    name_lower = team_name.lower()
    for t in data["data"]:
        full = t.get("full_name", "").lower()
        city = t.get("city", "").lower()
        abbr = t.get("abbreviation", "").lower()
        if name_lower in full or name_lower == city or name_lower == abbr:
            team = t
            break

    if not team:
        logger.info("NBA team not found: %s", team_name)
        return {}

    team_id = team.get("id")

    # Fetch recent games for the team
    games_data = _safe_request(
        "GET", f"{BDL_BASE}/games",
        limiter=_bdl_limiter,
        params={
            "seasons[]": season,
            "team_ids[]": team_id,
            "per_page": 15,
        },
    )

    if not games_data or not games_data.get("data"):
        return {
            "team": team.get("full_name", team_name),
            "abbreviation": team.get("abbreviation", ""),
            "conference": team.get("conference", ""),
        }

    games = games_data["data"]

    # Compute aggregates
    total_pts = 0
    total_opp = 0
    wins = 0
    losses = 0

    for g in games:
        is_home = g.get("home_team", {}).get("id") == team_id
        if is_home:
            pts = g.get("home_team_score", 0) or 0
            opp = g.get("visitor_team_score", 0) or 0
        else:
            pts = g.get("visitor_team_score", 0) or 0
            opp = g.get("home_team_score", 0) or 0

        total_pts += pts
        total_opp += opp
        if pts > opp:
            wins += 1
        elif opp > pts:
            losses += 1

    n = len(games)
    return {
        "team": team.get("full_name", team_name),
        "abbreviation": team.get("abbreviation", ""),
        "conference": team.get("conference", ""),
        "games_sampled": n,
        "ppg": round(total_pts / max(n, 1), 1),
        "opp_ppg": round(total_opp / max(n, 1), 1),
        "last_n_record": f"{wins}-{losses}",
        "last_n": n,
    }


def get_nba_player_comparison(
    player_a: str,
    player_b: str,
    season: int = 2025,
) -> dict:
    """
    Compare two NBA players' season averages side by side.

    Returns dict with 'player_a' and 'player_b' stat blocks plus 'edges'.
    """
    stats_a = _get_nba_player_stats(player_a, season)
    stats_b = _get_nba_player_stats(player_b, season)

    if not stats_a or not stats_b:
        return {"player_a": stats_a, "player_b": stats_b, "edges": {}}

    # Determine edge for each category
    compare_keys = [
        ("pts", True), ("reb", True), ("ast", True),
        ("stl", True), ("blk", True), ("fg_pct", True),
        ("ft_pct", True), ("fg3m", True), ("tov", False),
    ]

    edges = {}
    for key, higher_is_better in compare_keys:
        a_val = _safe_float(stats_a.get(key, 0))
        b_val = _safe_float(stats_b.get(key, 0))
        if a_val == b_val:
            edges[key] = "even"
        elif (a_val > b_val) == higher_is_better:
            edges[key] = "a"
        else:
            edges[key] = "b"

    return {
        "player_a": stats_a,
        "player_b": stats_b,
        "edges": edges,
    }


def _get_nba_player_stats(player_name: str, season: int = 2025) -> dict:
    """Fetch NBA player season averages."""
    # Search for player
    data = _safe_request(
        "GET", f"{BDL_BASE}/players",
        limiter=_bdl_limiter,
        params={"search": player_name, "per_page": 5},
    )
    if not data or not data.get("data"):
        return {}

    # Find best match
    player = None
    name_lower = player_name.lower()
    for p in data["data"]:
        full = f"{p.get('first_name', '')} {p.get('last_name', '')}".lower()
        if full == name_lower:
            player = p
            break
    if not player:
        player = data["data"][0]

    player_id = player.get("id")

    # Get season averages
    avg_data = _safe_request(
        "GET", f"{BDL_BASE}/season_averages",
        limiter=_bdl_limiter,
        params={"season": season, "player_ids[]": player_id},
    )

    if not avg_data or not avg_data.get("data"):
        return {}

    avg = avg_data["data"][0]
    team = player.get("team", {})

    return {
        "name": f"{player.get('first_name', '')} {player.get('last_name', '')}",
        "team": team.get("abbreviation", ""),
        "position": player.get("position", ""),
        "games_played": avg.get("games_played", 0),
        "pts": avg.get("pts", 0.0),
        "reb": avg.get("reb", 0.0),
        "ast": avg.get("ast", 0.0),
        "stl": avg.get("stl", 0.0),
        "blk": avg.get("blk", 0.0),
        "tov": avg.get("turnover", 0.0),
        "fg_pct": avg.get("fg_pct", 0.0),
        "ft_pct": avg.get("ft_pct", 0.0),
        "fg3_pct": avg.get("fg3_pct", 0.0),
        "fg3m": avg.get("fg3m", 0.0),
        "min": avg.get("min", "0"),
    }


# ===========================================================================
# MLB Stats API — statsapi.mlb.com
# ===========================================================================

MLB_BASE = "https://statsapi.mlb.com/api/v1"

# Team name to ID mapping (2026 season)
MLB_TEAM_IDS = {
    "yankees": 147, "red sox": 111, "dodgers": 119, "mets": 121,
    "braves": 144, "astros": 117, "phillies": 143, "padres": 135,
    "cubs": 112, "cardinals": 138, "giants": 137, "mariners": 136,
    "orioles": 110, "guardians": 114, "rangers": 140, "twins": 142,
    "rays": 139, "blue jays": 141, "tigers": 116, "brewers": 158,
    "reds": 113, "pirates": 134, "nationals": 120, "marlins": 146,
    "diamondbacks": 109, "rockies": 115, "royals": 118, "white sox": 145,
    "angels": 108, "athletics": 133,
}


def _resolve_mlb_team_id(team_name: str) -> Optional[int]:
    """Resolve a team name to its MLB Stats API ID."""
    name_lower = team_name.lower().strip()
    for key, tid in MLB_TEAM_IDS.items():
        if key in name_lower or name_lower in key:
            return tid
    return None


def get_mlb_team_stats(team_name: str, season: int = 2025) -> dict:
    """
    Get MLB team season stats.

    Returns dict with team record, batting stats, and pitching stats.
    """
    team_id = _resolve_mlb_team_id(team_name)
    if not team_id:
        logger.info("MLB team not found: %s", team_name)
        return {}

    # Get team record
    standings = _safe_request(
        "GET", f"{MLB_BASE}/standings",
        limiter=_mlb_limiter,
        params={"leagueId": "103,104", "season": season},
    )

    record = {}
    if standings:
        for division in standings.get("records", []):
            for team in division.get("teamRecords", []):
                if team.get("team", {}).get("id") == team_id:
                    record = {
                        "wins": team.get("wins", 0),
                        "losses": team.get("losses", 0),
                        "pct": team.get("winningPercentage", ".000"),
                        "division_rank": team.get("divisionRank", ""),
                        "streak": team.get("streak", {}).get("streakCode", ""),
                    }
                    break

    # Get team batting stats
    batting = _safe_request(
        "GET", f"{MLB_BASE}/teams/{team_id}/stats",
        limiter=_mlb_limiter,
        params={"stats": "season", "season": season, "group": "hitting"},
    )

    batting_stats = {}
    if batting and batting.get("stats"):
        splits = batting["stats"][0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            batting_stats = {
                "avg": s.get("avg", ".000"),
                "hr": s.get("homeRuns", 0),
                "runs": s.get("runs", 0),
                "rbi": s.get("rbi", 0),
                "obp": s.get("obp", ".000"),
                "slg": s.get("slg", ".000"),
                "ops": s.get("ops", ".000"),
                "sb": s.get("stolenBases", 0),
            }

    # Get team pitching stats
    pitching = _safe_request(
        "GET", f"{MLB_BASE}/teams/{team_id}/stats",
        limiter=_mlb_limiter,
        params={"stats": "season", "season": season, "group": "pitching"},
    )

    pitching_stats = {}
    if pitching and pitching.get("stats"):
        splits = pitching["stats"][0].get("splits", [])
        if splits:
            s = splits[0].get("stat", {})
            pitching_stats = {
                "era": s.get("era", "0.00"),
                "whip": s.get("whip", "0.00"),
                "so": s.get("strikeOuts", 0),
                "bb": s.get("baseOnBalls", 0),
                "saves": s.get("saves", 0),
                "hits_per_9": s.get("hitsPer9Inn", "0.00"),
                "hr_per_9": s.get("homeRunsPer9", "0.00"),
            }

    return {
        "team": team_name,
        "team_id": team_id,
        "record": record,
        "batting": batting_stats,
        "pitching": pitching_stats,
    }


def get_mlb_probable_pitchers(game_pk: int) -> dict:
    """
    Get probable pitchers for a specific MLB game.

    Args:
        game_pk: MLB game primary key

    Returns dict with home_pitcher and away_pitcher info.
    """
    data = _safe_request(
        "GET", f"{MLB_BASE}/schedule",
        limiter=_mlb_limiter,
        params={"gamePk": game_pk, "hydrate": "probablePitcher"},
    )

    if not data:
        return {}

    dates = data.get("dates", [])
    if not dates:
        return {}

    games = dates[0].get("games", [])
    if not games:
        return {}

    game = games[0]
    teams = game.get("teams", {})

    result = {}
    for side in ("home", "away"):
        pitcher = teams.get(side, {}).get("probablePitcher", {})
        if pitcher:
            result[f"{side}_pitcher"] = {
                "id": pitcher.get("id"),
                "name": pitcher.get("fullName", "TBD"),
            }
        else:
            result[f"{side}_pitcher"] = {"name": "TBD"}

    return result


def get_mlb_pitcher_vs_batter(
    pitcher_id: int,
    batter_ids: list[int],
    season: int = 2025,
) -> dict:
    """
    Get pitcher vs batter matchup stats.

    Returns dict mapping batter_id to their stats vs the pitcher.
    """
    results = {}
    for batter_id in batter_ids:
        data = _safe_request(
            "GET", f"{MLB_BASE}/people/{pitcher_id}/stats",
            limiter=_mlb_limiter,
            params={
                "stats": "vsPlayer",
                "opposingPlayerId": batter_id,
                "season": season,
                "group": "pitching",
            },
        )

        if not data or not data.get("stats"):
            results[batter_id] = {}
            continue

        splits = data["stats"][0].get("splits", [])
        if not splits:
            results[batter_id] = {}
            continue

        s = splits[0].get("stat", {})
        results[batter_id] = {
            "ab": s.get("atBats", 0),
            "hits": s.get("hits", 0),
            "hr": s.get("homeRuns", 0),
            "so": s.get("strikeOuts", 0),
            "bb": s.get("baseOnBalls", 0),
            "avg": s.get("avg", ".000"),
        }

    return results


# ===========================================================================
# football-data.org — Soccer
# ===========================================================================

FBD_BASE = "https://api.football-data.org/v4"

# Competition codes for common leagues
SOCCER_COMPETITIONS = {
    "premier_league": "PL",
    "la_liga": "PD",
    "bundesliga": "BL1",
    "serie_a": "SA",
    "ligue_1": "FL1",
    "champions_league": "CL",
}


def _fbd_headers() -> dict:
    """Get headers for football-data.org requests."""
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Auth-Token"] = key
    return headers


def get_soccer_standings(competition: str = "premier_league") -> list[dict]:
    """
    Get league standings for a soccer competition.

    Args:
        competition: Competition key (see SOCCER_COMPETITIONS)

    Returns list of team standings dicts sorted by position.
    """
    code = SOCCER_COMPETITIONS.get(competition.lower(), competition.upper())

    data = _safe_request(
        "GET", f"{FBD_BASE}/competitions/{code}/standings",
        limiter=_fbd_limiter,
        headers=_fbd_headers(),
    )

    if not data:
        return []

    standings_list = data.get("standings", [])
    if not standings_list:
        return []

    # Use total standings (not home/away splits)
    total = None
    for s in standings_list:
        if s.get("type") == "TOTAL":
            total = s
            break
    if not total:
        total = standings_list[0]

    result = []
    for entry in total.get("table", []):
        team = entry.get("team", {})
        result.append({
            "position": entry.get("position", 0),
            "team": team.get("name", ""),
            "team_id": team.get("id"),
            "short_name": team.get("shortName", ""),
            "played": entry.get("playedGames", 0),
            "won": entry.get("won", 0),
            "draw": entry.get("draw", 0),
            "lost": entry.get("lost", 0),
            "goals_for": entry.get("goalsFor", 0),
            "goals_against": entry.get("goalsAgainst", 0),
            "goal_diff": entry.get("goalDifference", 0),
            "points": entry.get("points", 0),
            "form": entry.get("form", ""),
        })

    return result


def get_soccer_head_to_head(team_a_id: int, team_b_id: int) -> dict:
    """
    Get head-to-head record between two soccer teams.

    Note: football-data.org provides h2h via match endpoint.
    Returns summary of recent meetings.
    """
    data = _safe_request(
        "GET", f"{FBD_BASE}/teams/{team_a_id}/matches",
        limiter=_fbd_limiter,
        headers=_fbd_headers(),
        params={"status": "FINISHED", "limit": 50},
    )

    if not data or not data.get("matches"):
        return {"matches": 0, "team_a_wins": 0, "team_b_wins": 0, "draws": 0}

    h2h_matches = []
    for match in data["matches"]:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")
        if {home_id, away_id} == {team_a_id, team_b_id}:
            h2h_matches.append(match)

    if not h2h_matches:
        return {"matches": 0, "team_a_wins": 0, "team_b_wins": 0, "draws": 0}

    a_wins = 0
    b_wins = 0
    draws = 0
    total_a_goals = 0
    total_b_goals = 0

    for m in h2h_matches:
        home_id = m.get("homeTeam", {}).get("id")
        ft = m.get("score", {}).get("fullTime", {})
        home_goals = ft.get("home", 0) or 0
        away_goals = ft.get("away", 0) or 0

        if home_id == team_a_id:
            a_goals = home_goals
            b_goals = away_goals
        else:
            a_goals = away_goals
            b_goals = home_goals

        total_a_goals += a_goals
        total_b_goals += b_goals

        if a_goals > b_goals:
            a_wins += 1
        elif b_goals > a_goals:
            b_wins += 1
        else:
            draws += 1

    return {
        "matches": len(h2h_matches),
        "team_a_wins": a_wins,
        "team_b_wins": b_wins,
        "draws": draws,
        "team_a_goals": total_a_goals,
        "team_b_goals": total_b_goals,
    }


def get_soccer_team_info(team_name: str, competition: str = "premier_league") -> dict:
    """
    Find a soccer team by name within a competition and return team info.

    Returns dict with team_id, name, standings position, form.
    """
    standings = get_soccer_standings(competition)
    if not standings:
        return {}

    name_lower = team_name.lower()
    for entry in standings:
        team = entry.get("team", "") or ""
        short = entry.get("short_name", "") or ""
        if (
            name_lower in team.lower()
            or name_lower in short.lower()
            or team.lower() in name_lower
        ):
            return entry

    return {}


# ===========================================================================
# Helpers
# ===========================================================================

def _safe_float(value) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
