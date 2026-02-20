"""
Comprehensive tests for matchup-analyzer: data_sources.py and analyzer.py.

All HTTP requests are mocked via unittest.mock so no real network calls are made.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Ensure the scripts directory is importable
# ---------------------------------------------------------------------------
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, "scripts"
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

import data_sources  # noqa: E402
from data_sources import (
    RateLimiter,
    _safe_request,
    _safe_float,
    _resolve_mlb_team_id,
    get_nba_team_stats,
    get_nba_player_comparison,
    get_mlb_team_stats,
    get_mlb_probable_pitchers,
    get_mlb_pitcher_vs_batter,
    get_soccer_standings,
    get_soccer_head_to_head,
    get_soccer_team_info,
)

import analyzer  # noqa: E402
from analyzer import (
    _compute_edge,
    _safe_float as analyzer_safe_float,
    build_nba_team_matchup,
    build_nba_player_matchup,
    build_mlb_team_matchup,
    build_soccer_matchup,
    ShippSchedule,
)


# ============================================================================
# Helper: build a mock Response
# ============================================================================

def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ============================================================================
# 1. RateLimiter tests
# ============================================================================

class TestRateLimiter(unittest.TestCase):

    @patch("data_sources.time.sleep")
    @patch("data_sources.time.time")
    def test_rate_limiter_waits_when_too_fast(self, mock_time, mock_sleep):
        """RateLimiter.wait() should sleep when called within min_interval."""
        rl = RateLimiter(2.0)
        # First call: time() returns 100 on entry, 100 when setting last_request
        mock_time.side_effect = [100.0, 100.0]
        rl.wait()
        mock_sleep.assert_not_called()  # first call never sleeps

        # Second call: only 0.5 s elapsed -> should sleep 1.5 s
        mock_time.side_effect = [100.5, 102.0]
        rl.wait()
        mock_sleep.assert_called_once_with(1.5)

    @patch("data_sources.time.sleep")
    @patch("data_sources.time.time")
    def test_rate_limiter_no_wait_when_enough_time_elapsed(self, mock_time, mock_sleep):
        """RateLimiter.wait() should not sleep when min_interval already passed."""
        rl = RateLimiter(1.0)
        rl.last_request = 50.0
        mock_time.side_effect = [52.0, 52.0]
        rl.wait()
        mock_sleep.assert_not_called()


# ============================================================================
# 2. _safe_request tests
# ============================================================================

class TestSafeRequest(unittest.TestCase):

    @patch("data_sources.requests.request")
    def test_safe_request_success(self, mock_req):
        """Successful 200 response returns parsed JSON."""
        limiter = RateLimiter(0)
        limiter.last_request = 0
        mock_req.return_value = _mock_response(200, {"ok": True})

        result = _safe_request("GET", "http://example.com", limiter)
        self.assertEqual(result, {"ok": True})

    @patch("data_sources.time.sleep")
    @patch("data_sources.requests.request")
    def test_safe_request_rate_limited_429(self, mock_req, mock_sleep):
        """429 response triggers a 30-second backoff and returns None."""
        limiter = RateLimiter(0)
        limiter.last_request = 0
        mock_req.return_value = _mock_response(429)

        result = _safe_request("GET", "http://example.com", limiter)
        self.assertIsNone(result)
        mock_sleep.assert_any_call(30)

    @patch("data_sources.requests.request")
    def test_safe_request_server_error(self, mock_req):
        """Non-200 / non-429 status returns None."""
        limiter = RateLimiter(0)
        limiter.last_request = 0
        mock_req.return_value = _mock_response(500, text="Internal Server Error")

        result = _safe_request("GET", "http://example.com", limiter)
        self.assertIsNone(result)

    @patch("data_sources.requests.request")
    def test_safe_request_network_exception(self, mock_req):
        """Network-level exception returns None."""
        import requests as real_requests
        limiter = RateLimiter(0)
        limiter.last_request = 0
        mock_req.side_effect = real_requests.ConnectionError("DNS failure")

        result = _safe_request("GET", "http://example.com", limiter)
        self.assertIsNone(result)


# ============================================================================
# 3. _safe_float / _resolve_mlb_team_id helpers
# ============================================================================

class TestHelpers(unittest.TestCase):

    def test_safe_float_valid(self):
        self.assertEqual(_safe_float(3.14), 3.14)
        self.assertEqual(_safe_float("2.5"), 2.5)

    def test_safe_float_invalid(self):
        self.assertEqual(_safe_float("not-a-number"), 0.0)
        self.assertEqual(_safe_float(None), 0.0)

    def test_resolve_mlb_team_id_known(self):
        self.assertEqual(_resolve_mlb_team_id("Yankees"), 147)
        self.assertEqual(_resolve_mlb_team_id("red sox"), 111)

    def test_resolve_mlb_team_id_unknown(self):
        self.assertIsNone(_resolve_mlb_team_id("Narwhals"))


# ============================================================================
# 4. NBA data fetching
# ============================================================================

class TestNBATeamStats(unittest.TestCase):

    @patch("data_sources._safe_request")
    def test_get_nba_team_stats_full(self, mock_sr):
        """Happy path: team found, games returned, averages computed."""
        teams_resp = {
            "data": [
                {
                    "id": 14,
                    "full_name": "Los Angeles Lakers",
                    "city": "Los Angeles",
                    "abbreviation": "LAL",
                    "conference": "West",
                },
            ],
        }
        games_resp = {
            "data": [
                {
                    "home_team": {"id": 14},
                    "home_team_score": 110,
                    "visitor_team_score": 105,
                },
                {
                    "home_team": {"id": 99},
                    "visitor_team": {"id": 14},
                    "home_team_score": 98,
                    "visitor_team_score": 102,
                },
            ],
        }
        mock_sr.side_effect = [teams_resp, games_resp]

        stats = get_nba_team_stats("Lakers")

        self.assertEqual(stats["team"], "Los Angeles Lakers")
        self.assertEqual(stats["abbreviation"], "LAL")
        self.assertEqual(stats["games_sampled"], 2)
        # ppg = (110+102)/2 = 106.0, opp_ppg = (105+98)/2 = 101.5
        self.assertAlmostEqual(stats["ppg"], 106.0)
        self.assertAlmostEqual(stats["opp_ppg"], 101.5)
        self.assertEqual(stats["last_n_record"], "2-0")

    @patch("data_sources._safe_request")
    def test_get_nba_team_stats_team_not_found(self, mock_sr):
        """When team lookup returns no match, return empty dict."""
        mock_sr.return_value = {
            "data": [
                {"id": 1, "full_name": "Atlanta Hawks", "city": "Atlanta", "abbreviation": "ATL"},
            ],
        }
        result = get_nba_team_stats("Nonexistent Team")
        self.assertEqual(result, {})

    @patch("data_sources._safe_request")
    def test_get_nba_team_stats_api_failure(self, mock_sr):
        """API returning None (failure) yields empty dict."""
        mock_sr.return_value = None
        result = get_nba_team_stats("Lakers")
        self.assertEqual(result, {})

    @patch("data_sources._safe_request")
    def test_get_nba_team_stats_no_games(self, mock_sr):
        """Team found but no games data returns minimal info."""
        teams_resp = {
            "data": [
                {
                    "id": 14,
                    "full_name": "Los Angeles Lakers",
                    "city": "Los Angeles",
                    "abbreviation": "LAL",
                    "conference": "West",
                },
            ],
        }
        mock_sr.side_effect = [teams_resp, None]
        result = get_nba_team_stats("Lakers")
        self.assertEqual(result["team"], "Los Angeles Lakers")
        self.assertNotIn("ppg", result)


# ============================================================================
# 5. NBA player comparison
# ============================================================================

class TestNBAPlayerComparison(unittest.TestCase):

    @patch("data_sources._safe_request")
    def test_player_comparison_edges(self, mock_sr):
        """Player comparison correctly identifies edges."""
        # Player A search, Player A averages, Player B search, Player B averages
        player_a_search = {
            "data": [
                {"id": 237, "first_name": "LeBron", "last_name": "James", "position": "F", "team": {"abbreviation": "LAL"}},
            ],
        }
        player_a_avgs = {
            "data": [
                {"games_played": 50, "pts": 25.0, "reb": 7.0, "ast": 8.0, "stl": 1.2, "blk": 0.5, "turnover": 3.0, "fg_pct": 0.52, "ft_pct": 0.75, "fg3_pct": 0.38, "fg3m": 2.0, "min": "35"},
            ],
        }
        player_b_search = {
            "data": [
                {"id": 456, "first_name": "Jayson", "last_name": "Tatum", "position": "F", "team": {"abbreviation": "BOS"}},
            ],
        }
        player_b_avgs = {
            "data": [
                {"games_played": 55, "pts": 27.0, "reb": 8.5, "ast": 4.5, "stl": 1.0, "blk": 0.7, "turnover": 2.5, "fg_pct": 0.47, "ft_pct": 0.85, "fg3_pct": 0.37, "fg3m": 3.0, "min": "36"},
            ],
        }

        mock_sr.side_effect = [
            player_a_search, player_a_avgs,
            player_b_search, player_b_avgs,
        ]

        result = get_nba_player_comparison("LeBron James", "Jayson Tatum")

        self.assertIn("edges", result)
        edges = result["edges"]
        # Tatum scores more => pts edge = "b"
        self.assertEqual(edges["pts"], "b")
        # LeBron has more assists => ast edge = "a"
        self.assertEqual(edges["ast"], "a")
        # Turnovers: lower is better. LeBron 3.0 > Tatum 2.5, so Tatum is better => edge = "b"
        self.assertEqual(edges["tov"], "b")

    @patch("data_sources._safe_request")
    def test_player_comparison_missing_player(self, mock_sr):
        """If one player cannot be found, edges dict is empty."""
        mock_sr.side_effect = [None, None]  # both fail
        result = get_nba_player_comparison("Nobody", "Also Nobody")
        self.assertEqual(result["edges"], {})


# ============================================================================
# 6. MLB data fetching
# ============================================================================

class TestMLBTeamStats(unittest.TestCase):

    @patch("data_sources._safe_request")
    def test_get_mlb_team_stats_full(self, mock_sr):
        """Happy path for MLB team stats with standings, batting, pitching."""
        standings_resp = {
            "records": [
                {
                    "teamRecords": [
                        {
                            "team": {"id": 147},
                            "wins": 82,
                            "losses": 55,
                            "winningPercentage": ".599",
                            "divisionRank": "1",
                            "streak": {"streakCode": "W3"},
                        },
                    ],
                },
            ],
        }
        batting_resp = {
            "stats": [
                {
                    "splits": [
                        {
                            "stat": {
                                "avg": ".265",
                                "homeRuns": 180,
                                "runs": 650,
                                "rbi": 620,
                                "obp": ".340",
                                "slg": ".450",
                                "ops": ".790",
                                "stolenBases": 90,
                            },
                        },
                    ],
                },
            ],
        }
        pitching_resp = {
            "stats": [
                {
                    "splits": [
                        {
                            "stat": {
                                "era": "3.45",
                                "whip": "1.20",
                                "strikeOuts": 1100,
                                "baseOnBalls": 400,
                                "saves": 40,
                                "hitsPer9Inn": "8.0",
                                "homeRunsPer9": "1.1",
                            },
                        },
                    ],
                },
            ],
        }

        mock_sr.side_effect = [standings_resp, batting_resp, pitching_resp]

        stats = get_mlb_team_stats("Yankees")

        self.assertEqual(stats["team_id"], 147)
        self.assertEqual(stats["record"]["wins"], 82)
        self.assertEqual(stats["batting"]["avg"], ".265")
        self.assertEqual(stats["pitching"]["era"], "3.45")

    @patch("data_sources._safe_request")
    def test_get_mlb_team_stats_unknown_team(self, mock_sr):
        """Unknown team name returns empty dict without any API calls."""
        result = get_mlb_team_stats("Unicorns")
        self.assertEqual(result, {})
        mock_sr.assert_not_called()


# ============================================================================
# 7. MLB probable pitchers
# ============================================================================

class TestMLBProbablePitchers(unittest.TestCase):

    @patch("data_sources._safe_request")
    def test_probable_pitchers_found(self, mock_sr):
        mock_sr.return_value = {
            "dates": [
                {
                    "games": [
                        {
                            "teams": {
                                "home": {
                                    "probablePitcher": {"id": 10, "fullName": "Ace McThrow"},
                                },
                                "away": {
                                    "probablePitcher": {"id": 20, "fullName": "Slider Steve"},
                                },
                            },
                        },
                    ],
                },
            ],
        }
        result = get_mlb_probable_pitchers(123456)
        self.assertEqual(result["home_pitcher"]["name"], "Ace McThrow")
        self.assertEqual(result["away_pitcher"]["name"], "Slider Steve")

    @patch("data_sources._safe_request")
    def test_probable_pitchers_tbd(self, mock_sr):
        """When no probable pitcher is set, name should be TBD."""
        mock_sr.return_value = {
            "dates": [
                {
                    "games": [
                        {
                            "teams": {
                                "home": {},
                                "away": {},
                            },
                        },
                    ],
                },
            ],
        }
        result = get_mlb_probable_pitchers(123456)
        self.assertEqual(result["home_pitcher"]["name"], "TBD")
        self.assertEqual(result["away_pitcher"]["name"], "TBD")

    @patch("data_sources._safe_request")
    def test_probable_pitchers_empty_response(self, mock_sr):
        mock_sr.return_value = None
        result = get_mlb_probable_pitchers(999)
        self.assertEqual(result, {})


# ============================================================================
# 8. MLB pitcher vs batter
# ============================================================================

class TestMLBPitcherVsBatter(unittest.TestCase):

    @patch("data_sources._safe_request")
    def test_pitcher_vs_batter_stats(self, mock_sr):
        mock_sr.return_value = {
            "stats": [
                {
                    "splits": [
                        {
                            "stat": {
                                "atBats": 12,
                                "hits": 4,
                                "homeRuns": 1,
                                "strikeOuts": 3,
                                "baseOnBalls": 2,
                                "avg": ".333",
                            },
                        },
                    ],
                },
            ],
        }
        result = get_mlb_pitcher_vs_batter(10, [100])
        self.assertEqual(result[100]["ab"], 12)
        self.assertEqual(result[100]["avg"], ".333")

    @patch("data_sources._safe_request")
    def test_pitcher_vs_batter_no_data(self, mock_sr):
        mock_sr.return_value = None
        result = get_mlb_pitcher_vs_batter(10, [100, 200])
        self.assertEqual(result[100], {})
        self.assertEqual(result[200], {})


# ============================================================================
# 9. Soccer data fetching
# ============================================================================

class TestSoccer(unittest.TestCase):

    @patch("data_sources._safe_request")
    def test_get_soccer_standings(self, mock_sr):
        mock_sr.return_value = {
            "standings": [
                {
                    "type": "TOTAL",
                    "table": [
                        {
                            "position": 1,
                            "team": {"name": "Arsenal FC", "id": 57, "shortName": "Arsenal"},
                            "playedGames": 25,
                            "won": 18,
                            "draw": 4,
                            "lost": 3,
                            "goalsFor": 55,
                            "goalsAgainst": 20,
                            "goalDifference": 35,
                            "points": 58,
                            "form": "W,W,D,W,L",
                        },
                    ],
                },
            ],
        }
        result = get_soccer_standings("premier_league")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["team"], "Arsenal FC")
        self.assertEqual(result[0]["points"], 58)

    @patch("data_sources._safe_request")
    def test_get_soccer_standings_empty(self, mock_sr):
        mock_sr.return_value = None
        result = get_soccer_standings("premier_league")
        self.assertEqual(result, [])

    @patch("data_sources._safe_request")
    def test_get_soccer_head_to_head(self, mock_sr):
        """H2H correctly filters and tallies results."""
        mock_sr.return_value = {
            "matches": [
                {
                    "homeTeam": {"id": 57},
                    "awayTeam": {"id": 65},
                    "score": {"fullTime": {"home": 3, "away": 1}},
                },
                {
                    "homeTeam": {"id": 65},
                    "awayTeam": {"id": 57},
                    "score": {"fullTime": {"home": 2, "away": 2}},
                },
                # A match not involving team_b should be excluded
                {
                    "homeTeam": {"id": 57},
                    "awayTeam": {"id": 999},
                    "score": {"fullTime": {"home": 1, "away": 0}},
                },
            ],
        }
        result = get_soccer_head_to_head(57, 65)
        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["team_a_wins"], 1)
        self.assertEqual(result["draws"], 1)
        self.assertEqual(result["team_b_wins"], 0)
        # Goals: match1 A=3 B=1, match2 A(away)=2 B(home)=2 => total A=5 B=3
        self.assertEqual(result["team_a_goals"], 5)
        self.assertEqual(result["team_b_goals"], 3)

    @patch("data_sources._safe_request")
    def test_get_soccer_head_to_head_no_matches(self, mock_sr):
        mock_sr.return_value = {"matches": []}
        result = get_soccer_head_to_head(57, 65)
        self.assertEqual(result["matches"], 0)

    @patch("data_sources.get_soccer_standings")
    def test_get_soccer_team_info_found(self, mock_standings):
        mock_standings.return_value = [
            {"team": "Arsenal FC", "short_name": "Arsenal", "position": 1, "points": 58, "team_id": 57},
            {"team": "Manchester City FC", "short_name": "Man City", "position": 2, "points": 55, "team_id": 65},
        ]
        result = get_soccer_team_info("Arsenal")
        self.assertEqual(result["team_id"], 57)

    @patch("data_sources.get_soccer_standings")
    def test_get_soccer_team_info_not_found(self, mock_standings):
        mock_standings.return_value = [
            {"team": "Arsenal FC", "short_name": "Arsenal", "position": 1},
        ]
        result = get_soccer_team_info("Nonexistent FC")
        self.assertEqual(result, {})


# ============================================================================
# 10. _compute_edge (analyzer.py)
# ============================================================================

class TestComputeEdge(unittest.TestCase):

    def test_even(self):
        result = _compute_edge(10.0, 10.0, True, "A", "B")
        self.assertEqual(result, "EVEN")

    def test_higher_is_better_a_wins_big(self):
        # 20 vs 10 => 67% diff => ">>"
        result = _compute_edge(20.0, 10.0, True, "A", "B")
        self.assertIn("A", result)
        self.assertIn(">>", result)

    def test_higher_is_better_b_wins(self):
        result = _compute_edge(10.0, 20.0, True, "A", "B")
        self.assertIn("B", result)

    def test_lower_is_better(self):
        # Lower is better: A=3.0, B=4.0 => A wins
        result = _compute_edge(3.0, 4.0, False, "A", "B")
        self.assertIn("A", result)

    def test_non_numeric_returns_empty(self):
        result = _compute_edge("foo", "bar", True, "A", "B")
        self.assertEqual(result, "")

    def test_small_difference_tilde(self):
        # 100 vs 102 => ~2% diff => "~" prefix
        result = _compute_edge(100.0, 102.0, True, "A", "B")
        self.assertTrue(result.startswith("~"))


# ============================================================================
# 11. Matchup card builders (analyzer.py) — integration-style with mocks
# ============================================================================

class TestBuildMatchupCards(unittest.TestCase):

    @patch("analyzer.get_nba_team_stats")
    def test_build_nba_team_matchup_both_found(self, mock_stats):
        mock_stats.side_effect = [
            {
                "team": "Los Angeles Lakers",
                "abbreviation": "LAL",
                "conference": "West",
                "ppg": 112.5,
                "opp_ppg": 108.0,
                "last_n_record": "10-5",
            },
            {
                "team": "Boston Celtics",
                "abbreviation": "BOS",
                "conference": "East",
                "ppg": 118.0,
                "opp_ppg": 105.0,
                "last_n_record": "12-3",
            },
        ]
        card = build_nba_team_matchup("Lakers", "Celtics")
        self.assertIn("LAL", card)
        self.assertIn("BOS", card)
        self.assertIn("MATCHUP CARD -- NBA", card)
        self.assertIn("EDGE FACTORS", card)

    @patch("analyzer.get_nba_team_stats")
    def test_build_nba_team_matchup_both_missing(self, mock_stats):
        mock_stats.return_value = {}
        card = build_nba_team_matchup("FakeA", "FakeB")
        self.assertIn("Could not find stats", card)

    @patch("analyzer.get_mlb_team_stats")
    def test_build_mlb_team_matchup(self, mock_stats):
        mock_stats.side_effect = [
            {
                "team": "Yankees",
                "team_id": 147,
                "record": {"wins": 82, "losses": 55},
                "batting": {"avg": ".265", "ops": ".790", "hr": 180, "runs": 650, "rbi": 620, "sb": 90},
                "pitching": {"era": "3.45", "whip": "1.20", "so": 1100, "bb": 400, "saves": 40},
            },
            {
                "team": "Red Sox",
                "team_id": 111,
                "record": {"wins": 70, "losses": 67},
                "batting": {"avg": ".250", "ops": ".730", "hr": 150, "runs": 580, "rbi": 560, "sb": 70},
                "pitching": {"era": "4.10", "whip": "1.35", "so": 950, "bb": 450, "saves": 30},
            },
        ]
        card = build_mlb_team_matchup("Yankees", "Red Sox")
        self.assertIn("MATCHUP CARD -- MLB", card)
        self.assertIn("BATTING COMPARISON", card)
        self.assertIn("PITCHING COMPARISON", card)

    @patch("analyzer.get_soccer_head_to_head")
    @patch("analyzer.get_soccer_team_info")
    def test_build_soccer_matchup(self, mock_info, mock_h2h):
        mock_info.side_effect = [
            {
                "team": "Arsenal FC",
                "short_name": "Arsenal",
                "team_id": 57,
                "position": 1,
                "points": 58,
                "won": 18,
                "draw": 4,
                "lost": 3,
                "goals_for": 55,
                "goals_against": 20,
                "goal_diff": 35,
                "form": "W,W,D,W,L",
            },
            {
                "team": "Chelsea FC",
                "short_name": "Chelsea",
                "team_id": 61,
                "position": 4,
                "points": 45,
                "won": 13,
                "draw": 6,
                "lost": 6,
                "goals_for": 40,
                "goals_against": 30,
                "goal_diff": 10,
                "form": "W,L,W,D,W",
            },
        ]
        mock_h2h.return_value = {
            "matches": 3,
            "team_a_wins": 2,
            "team_b_wins": 0,
            "draws": 1,
            "team_a_goals": 6,
            "team_b_goals": 2,
        }
        card = build_soccer_matchup("Arsenal", "Chelsea")
        self.assertIn("Premier League", card)
        self.assertIn("HEAD-TO-HEAD", card)
        self.assertIn("EDGE FACTORS", card)


# ============================================================================
# 12. ShippSchedule
# ============================================================================

class TestShippSchedule(unittest.TestCase):

    @patch.object(ShippSchedule, "__init__", lambda self, key: None)
    def test_connect_success(self):
        sched = ShippSchedule.__new__(ShippSchedule)
        sched.api_key = "test-key"
        sched.session = MagicMock()
        sched.connection_id = None

        mock_resp = _mock_response(200, {"connection_id": "conn-123"})
        sched.session.post.return_value = mock_resp

        result = sched.connect("nba")
        self.assertTrue(result)
        self.assertEqual(sched.connection_id, "conn-123")

    @patch.object(ShippSchedule, "__init__", lambda self, key: None)
    def test_connect_failure(self):
        sched = ShippSchedule.__new__(ShippSchedule)
        sched.api_key = "test-key"
        sched.session = MagicMock()
        sched.connection_id = None

        sched.session.post.side_effect = Exception("Connection refused")

        result = sched.connect("nba")
        self.assertFalse(result)

    @patch.object(ShippSchedule, "__init__", lambda self, key: None)
    def test_get_today_games_no_connection(self):
        sched = ShippSchedule.__new__(ShippSchedule)
        sched.connection_id = None
        result = sched.get_today_games()
        self.assertEqual(result, [])

    @patch.object(ShippSchedule, "__init__", lambda self, key: None)
    def test_get_today_games_success(self):
        sched = ShippSchedule.__new__(ShippSchedule)
        sched.connection_id = "conn-123"
        sched.api_key = "test-key"
        sched.session = MagicMock()

        mock_resp = _mock_response(200, {"data": [{"home": "LAL", "away": "BOS"}]})
        sched.session.post.return_value = mock_resp

        result = sched.get_today_games()
        self.assertEqual(len(result), 1)


# ============================================================================
# 13. analyzer._safe_float
# ============================================================================

class TestAnalyzerSafeFloat(unittest.TestCase):

    def test_valid_values(self):
        self.assertEqual(analyzer_safe_float(5), 5.0)
        self.assertEqual(analyzer_safe_float("3.14"), 3.14)

    def test_invalid_values(self):
        self.assertEqual(analyzer_safe_float("abc"), 0.0)
        self.assertEqual(analyzer_safe_float(None), 0.0)


# ============================================================================
# Run
# ============================================================================

if __name__ == "__main__":
    unittest.main()
