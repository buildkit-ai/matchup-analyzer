#!/usr/bin/env python3
"""
Matchup Analyzer — Head-to-head team and player comparison.

Produces structured matchup reports for NBA, MLB, and Soccer by combining
live schedule data with stats from multiple external sources.

Usage:
    python analyzer.py --sport nba --teams "Lakers,Celtics"
    python analyzer.py --sport mlb --teams "Yankees,Red Sox"
    python analyzer.py --sport soccer --teams "Arsenal,Bayern Munich"
    python analyzer.py --sport nba --players "LeBron James,Jayson Tatum"
    python analyzer.py --sport nba --today
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests

from .data_sources import (
    get_nba_team_stats,
    get_nba_player_comparison,
    get_mlb_team_stats,
    get_mlb_probable_pitchers,
    get_soccer_standings,
    get_soccer_team_info,
    get_soccer_head_to_head,
)

logger = logging.getLogger(__name__)

SHIPP_BASE_URL = "https://api.shipp.ai/api/v1"

# ---------------------------------------------------------------------------
# Shipp Schedule Client
# ---------------------------------------------------------------------------


class ShippSchedule:
    """Fetches today's schedule and live game context via Shipp."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "matchup-analyzer/1.0",
        })
        self.connection_id: Optional[str] = None

    def _url(self, path: str) -> str:
        """Build URL with api_key query parameter."""
        sep = "&" if "?" in path else "?"
        return f"{SHIPP_BASE_URL}{path}{sep}api_key={self.api_key}"

    def connect(self, sport: str) -> bool:
        filter_map = {
            "nba": "Track all NBA games today with scores, schedule, and game status",
            "mlb": "Track all MLB games today with scores, schedule, and game status",
            "soccer": "Track all soccer matches today with scores, schedule, and game status",
        }
        try:
            resp = self.session.post(
                self._url("/connections/create"),
                json={
                    "filter_instructions": filter_map.get(sport, f"Track all {sport} games today with scores and schedule"),
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self.connection_id = data.get("connection_id") or data.get("id")
            return self.connection_id is not None
        except Exception as exc:
            logger.warning("Shipp connection failed: %s", exc)
            return False

    def get_today_games(self) -> list[dict]:
        """Get today's scheduled and live games."""
        if not self.connection_id:
            return []
        try:
            resp = self.session.post(
                self._url(f"/connections/{self.connection_id}"),
                json={"limit": 50},
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data.get("games") or data.get("scoreboard") or data.get("schedule") or [])
        except Exception as exc:
            logger.warning("Failed to fetch schedule: %s", exc)
            return []

    def close(self):
        if self.connection_id:
            try:
                self.session.post(
                    self._url(f"/connections/{self.connection_id}/close"),
                    json={},
                    timeout=5,
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Matchup Card Builders
# ---------------------------------------------------------------------------


def build_nba_team_matchup(team_a: str, team_b: str) -> str:
    """Build a full NBA team vs team matchup card."""
    print(f"  Fetching {team_a} stats...")
    stats_a = get_nba_team_stats(team_a)
    print(f"  Fetching {team_b} stats...")
    stats_b = get_nba_team_stats(team_b)

    if not stats_a and not stats_b:
        return f"Could not find stats for {team_a} or {team_b}."

    name_a = stats_a.get("abbreviation") or stats_a.get("team", team_a)
    name_b = stats_b.get("abbreviation") or stats_b.get("team", team_b)
    record_a = stats_a.get("last_n_record", "")
    record_b = stats_b.get("last_n_record", "")

    today = datetime.now().strftime("%b %d, %Y")

    lines = []
    lines.append("=" * 60)
    lines.append(f"  MATCHUP CARD -- NBA")
    lines.append(
        f"  {name_a} ({record_a}) vs {name_b} ({record_b})"
    )
    lines.append(f"  {today}")
    lines.append("=" * 60)
    lines.append("")

    # Team comparison table
    lines.append("  TEAM COMPARISON (recent games)")
    lines.append("  " + "-" * 56)
    lines.append(
        f"  {'Category':<18} {name_a:>10} {name_b:>10}   {'Edge':>8}"
    )
    lines.append("  " + "-" * 56)

    comparisons = [
        ("PPG", stats_a.get("ppg", 0), stats_b.get("ppg", 0), True),
        ("Opp PPG", stats_a.get("opp_ppg", 0), stats_b.get("opp_ppg", 0), False),
    ]

    for cat, val_a, val_b, higher_is_better in comparisons:
        edge = _compute_edge(val_a, val_b, higher_is_better, name_a, name_b)
        lines.append(
            f"  {cat:<18} {val_a:>10.1f} {val_b:>10.1f}   {edge:>8}"
        )

    record_line = f"  {'Last N Record':<18} {record_a:>10} {record_b:>10}"
    lines.append(record_line)

    lines.append("  " + "-" * 56)
    lines.append("")

    # Edge factors summary
    lines.append("  EDGE FACTORS")

    a_ppg = stats_a.get("ppg", 0) or 0
    b_ppg = stats_b.get("ppg", 0) or 0
    a_opp = stats_a.get("opp_ppg", 0) or 0
    b_opp = stats_b.get("opp_ppg", 0) or 0

    net_a = a_ppg - a_opp
    net_b = b_ppg - b_opp

    if net_a > net_b:
        lines.append(f"  + {name_a}: Better net rating ({net_a:+.1f} vs {net_b:+.1f})")
    elif net_b > net_a:
        lines.append(f"  + {name_b}: Better net rating ({net_b:+.1f} vs {net_a:+.1f})")

    if a_ppg > b_ppg:
        lines.append(f"  + {name_a}: Higher-scoring offense ({a_ppg:.1f} PPG)")
    elif b_ppg > a_ppg:
        lines.append(f"  + {name_b}: Higher-scoring offense ({b_ppg:.1f} PPG)")

    if a_opp < b_opp:
        lines.append(f"  + {name_a}: Tougher defense ({a_opp:.1f} Opp PPG)")
    elif b_opp < a_opp:
        lines.append(f"  + {name_b}: Tougher defense ({b_opp:.1f} Opp PPG)")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def build_nba_player_matchup(player_a: str, player_b: str) -> str:
    """Build an NBA player vs player comparison card."""
    print(f"  Comparing {player_a} vs {player_b}...")
    comparison = get_nba_player_comparison(player_a, player_b)

    sa = comparison.get("player_a", {})
    sb = comparison.get("player_b", {})
    edges = comparison.get("edges", {})

    if not sa or not sb:
        missing = []
        if not sa:
            missing.append(player_a)
        if not sb:
            missing.append(player_b)
        return f"Could not find stats for: {', '.join(missing)}"

    name_a = sa.get("name", player_a)
    name_b = sb.get("name", player_b)
    team_a = sa.get("team", "")
    team_b = sb.get("team", "")
    pos_a = sa.get("position", "")
    pos_b = sb.get("position", "")

    lines = []
    lines.append("=" * 60)
    lines.append("  PLAYER COMPARISON -- NBA")
    lines.append(
        f"  {name_a} ({pos_a}, {team_a}) vs {name_b} ({pos_b}, {team_b})"
    )
    lines.append("=" * 60)
    lines.append("")

    # Stat comparison table
    stat_rows = [
        ("PTS", "pts", True),
        ("REB", "reb", True),
        ("AST", "ast", True),
        ("STL", "stl", True),
        ("BLK", "blk", True),
        ("TOV", "tov", False),
        ("FG%", "fg_pct", True),
        ("FT%", "ft_pct", True),
        ("3PM", "fg3m", True),
        ("MIN", "min", True),
    ]

    abbr_a = name_a.split()[-1][:6] if name_a else "A"
    abbr_b = name_b.split()[-1][:6] if name_b else "B"

    lines.append(
        f"  {'Stat':<10} {abbr_a:>10} {abbr_b:>10}   {'Edge':>8}"
    )
    lines.append("  " + "-" * 46)

    for label, key, higher_is_better in stat_rows:
        val_a = sa.get(key, 0)
        val_b = sb.get(key, 0)

        try:
            fa = float(val_a)
            fb = float(val_b)
            edge_marker = _compute_edge(fa, fb, higher_is_better, abbr_a, abbr_b)
            if key in ("fg_pct", "ft_pct", "fg3_pct"):
                lines.append(
                    f"  {label:<10} {fa:>10.3f} {fb:>10.3f}   {edge_marker:>8}"
                )
            else:
                lines.append(
                    f"  {label:<10} {fa:>10.1f} {fb:>10.1f}   {edge_marker:>8}"
                )
        except (ValueError, TypeError):
            lines.append(
                f"  {label:<10} {str(val_a):>10} {str(val_b):>10}"
            )

    lines.append("  " + "-" * 46)
    lines.append("")

    # Summary
    a_edges = sum(1 for v in edges.values() if v == "a")
    b_edges = sum(1 for v in edges.values() if v == "b")
    even = sum(1 for v in edges.values() if v == "even")

    lines.append("  SUMMARY")
    lines.append(f"  {name_a}: {a_edges} category edges")
    lines.append(f"  {name_b}: {b_edges} category edges")
    if even:
        lines.append(f"  Even: {even} categories")

    # Key edges
    key_edges_a = []
    key_edges_b = []
    for key, winner in edges.items():
        label = key.upper().replace("_", " ")
        if winner == "a":
            key_edges_a.append(label)
        elif winner == "b":
            key_edges_b.append(label)

    if key_edges_a:
        lines.append(f"\n  {name_a} advantages: {', '.join(key_edges_a)}")
    if key_edges_b:
        lines.append(f"  {name_b} advantages: {', '.join(key_edges_b)}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def build_mlb_team_matchup(team_a: str, team_b: str) -> str:
    """Build an MLB team vs team matchup card."""
    print(f"  Fetching {team_a} stats...")
    stats_a = get_mlb_team_stats(team_a)
    print(f"  Fetching {team_b} stats...")
    stats_b = get_mlb_team_stats(team_b)

    if not stats_a and not stats_b:
        return f"Could not find stats for {team_a} or {team_b}."

    rec_a = stats_a.get("record", {})
    rec_b = stats_b.get("record", {})
    bat_a = stats_a.get("batting", {})
    bat_b = stats_b.get("batting", {})
    pit_a = stats_a.get("pitching", {})
    pit_b = stats_b.get("pitching", {})

    record_str_a = f"{rec_a.get('wins', 0)}-{rec_a.get('losses', 0)}"
    record_str_b = f"{rec_b.get('wins', 0)}-{rec_b.get('losses', 0)}"

    today = datetime.now().strftime("%b %d, %Y")
    label_a = team_a.title()
    label_b = team_b.title()

    lines = []
    lines.append("=" * 60)
    lines.append("  MATCHUP CARD -- MLB")
    lines.append(f"  {label_a} ({record_str_a}) vs {label_b} ({record_str_b})")
    lines.append(f"  {today}")
    lines.append("=" * 60)
    lines.append("")

    # Batting comparison
    lines.append("  BATTING COMPARISON")
    lines.append("  " + "-" * 56)
    lines.append(
        f"  {'Category':<14} {label_a[:8]:>10} {label_b[:8]:>10}   {'Edge':>8}"
    )
    lines.append("  " + "-" * 56)

    batting_cats = [
        ("AVG", "avg", True, True),
        ("OPS", "ops", True, True),
        ("HR", "hr", True, False),
        ("Runs", "runs", True, False),
        ("RBI", "rbi", True, False),
        ("SB", "sb", True, False),
    ]

    for label, key, higher_is_better, is_pct in batting_cats:
        va = bat_a.get(key, 0)
        vb = bat_b.get(key, 0)
        try:
            fa = float(va) if isinstance(va, str) else va
            fb = float(vb) if isinstance(vb, str) else vb
            edge = _compute_edge(fa, fb, higher_is_better, label_a[:6], label_b[:6])
            if is_pct:
                lines.append(
                    f"  {label:<14} {str(va):>10} {str(vb):>10}   {edge:>8}"
                )
            else:
                lines.append(
                    f"  {label:<14} {fa:>10.0f} {fb:>10.0f}   {edge:>8}"
                )
        except (ValueError, TypeError):
            lines.append(f"  {label:<14} {str(va):>10} {str(vb):>10}")

    lines.append("")

    # Pitching comparison
    lines.append("  PITCHING COMPARISON")
    lines.append("  " + "-" * 56)
    lines.append(
        f"  {'Category':<14} {label_a[:8]:>10} {label_b[:8]:>10}   {'Edge':>8}"
    )
    lines.append("  " + "-" * 56)

    pitching_cats = [
        ("ERA", "era", False, True),
        ("WHIP", "whip", False, True),
        ("K", "so", True, False),
        ("BB", "bb", False, False),
        ("Saves", "saves", True, False),
    ]

    for label, key, higher_is_better, is_pct in pitching_cats:
        va = pit_a.get(key, 0)
        vb = pit_b.get(key, 0)
        try:
            fa = float(va) if isinstance(va, str) else va
            fb = float(vb) if isinstance(vb, str) else vb
            edge = _compute_edge(fa, fb, higher_is_better, label_a[:6], label_b[:6])
            if is_pct:
                lines.append(
                    f"  {label:<14} {str(va):>10} {str(vb):>10}   {edge:>8}"
                )
            else:
                lines.append(
                    f"  {label:<14} {fa:>10.0f} {fb:>10.0f}   {edge:>8}"
                )
        except (ValueError, TypeError):
            lines.append(f"  {label:<14} {str(va):>10} {str(vb):>10}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def build_soccer_matchup(
    team_a: str,
    team_b: str,
    competition: str = "premier_league",
) -> str:
    """Build a soccer matchup card with standings and head-to-head."""
    print(f"  Looking up {team_a} in {competition}...")
    info_a = get_soccer_team_info(team_a, competition)
    print(f"  Looking up {team_b} in {competition}...")
    info_b = get_soccer_team_info(team_b, competition)

    if not info_a and not info_b:
        return (
            f"Could not find {team_a} or {team_b} in {competition}. "
            "Try specifying the competition with --competition."
        )

    name_a = info_a.get("team") or info_a.get("short_name") or team_a
    name_b = info_b.get("team") or info_b.get("short_name") or team_b
    pos_a = info_a.get("position", "?")
    pos_b = info_b.get("position", "?")
    pts_a = info_a.get("points", 0)
    pts_b = info_b.get("points", 0)

    today = datetime.now().strftime("%b %d, %Y")
    comp_display = competition.replace("_", " ").title()

    lines = []
    lines.append("=" * 60)
    lines.append(f"  MATCHUP CARD -- {comp_display}")
    lines.append(f"  {name_a} vs {name_b}")
    lines.append(f"  {today}")
    lines.append("=" * 60)
    lines.append("")

    # League position comparison
    lines.append("  LEAGUE STANDING")
    lines.append("  " + "-" * 56)

    abbr_a = (info_a.get("short_name") or name_a)[:8]
    abbr_b = (info_b.get("short_name") or name_b)[:8]

    lines.append(
        f"  {'Category':<14} {abbr_a:>10} {abbr_b:>10}   {'Edge':>8}"
    )
    lines.append("  " + "-" * 56)

    standing_cats = [
        ("Position", "position", False),
        ("Points", "points", True),
        ("Won", "won", True),
        ("Draw", "draw", None),  # neutral
        ("Lost", "lost", False),
        ("GF", "goals_for", True),
        ("GA", "goals_against", False),
        ("GD", "goal_diff", True),
    ]

    for label, key, higher_is_better in standing_cats:
        va = info_a.get(key, 0)
        vb = info_b.get(key, 0)
        if higher_is_better is None:
            edge = ""
        else:
            edge = _compute_edge(va, vb, higher_is_better, abbr_a, abbr_b)
        lines.append(f"  {label:<14} {va:>10} {vb:>10}   {edge:>8}")

    # Form
    form_a = info_a.get("form", "")
    form_b = info_b.get("form", "")
    if form_a or form_b:
        lines.append("")
        lines.append(f"  Form: {abbr_a} {form_a}  |  {abbr_b} {form_b}")

    lines.append("")

    # Head-to-head if we have team IDs
    team_a_id = info_a.get("team_id")
    team_b_id = info_b.get("team_id")
    if team_a_id and team_b_id:
        print("  Fetching head-to-head record...")
        h2h = get_soccer_head_to_head(team_a_id, team_b_id)
        if h2h.get("matches", 0) > 0:
            lines.append("  HEAD-TO-HEAD (recent)")
            lines.append("  " + "-" * 40)
            lines.append(f"  Total matches: {h2h['matches']}")
            lines.append(f"  {name_a} wins: {h2h['team_a_wins']}")
            lines.append(f"  {name_b} wins: {h2h['team_b_wins']}")
            lines.append(f"  Draws: {h2h['draws']}")
            if h2h.get("team_a_goals") is not None:
                lines.append(
                    f"  Goals: {name_a} {h2h['team_a_goals']} - "
                    f"{h2h['team_b_goals']} {name_b}"
                )
            lines.append("")

    # Edge factors
    lines.append("  EDGE FACTORS")
    if pos_a < pos_b:
        lines.append(f"  + {name_a}: Higher league position ({pos_a} vs {pos_b})")
    elif pos_b < pos_a:
        lines.append(f"  + {name_b}: Higher league position ({pos_b} vs {pos_a})")

    gd_a = info_a.get("goal_diff", 0)
    gd_b = info_b.get("goal_diff", 0)
    if gd_a > gd_b:
        lines.append(f"  + {name_a}: Better goal difference ({gd_a:+d} vs {gd_b:+d})")
    elif gd_b > gd_a:
        lines.append(f"  + {name_b}: Better goal difference ({gd_b:+d} vs {gd_a:+d})")

    gf_a = info_a.get("goals_for", 0)
    gf_b = info_b.get("goals_for", 0)
    if gf_a > gf_b:
        lines.append(f"  + {name_a}: More prolific attack ({gf_a} goals scored)")
    elif gf_b > gf_a:
        lines.append(f"  + {name_b}: More prolific attack ({gf_b} goals scored)")

    ga_a = info_a.get("goals_against", 0)
    ga_b = info_b.get("goals_against", 0)
    if ga_a < ga_b:
        lines.append(f"  + {name_a}: Tighter defense ({ga_a} goals conceded)")
    elif ga_b < ga_a:
        lines.append(f"  + {name_b}: Tighter defense ({ga_b} goals conceded)")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Today's Games Preview
# ---------------------------------------------------------------------------


def preview_today(sport: str, competition: str = "premier_league"):
    """Generate matchup cards for all of today's games."""
    api_key = os.environ.get("SHIPP_API_KEY", "")
    if not api_key:
        print(
            "SHIPP_API_KEY required for today's schedule.\n"
            "Set: export SHIPP_API_KEY='your-key'\n"
            "Get free key: https://platform.shipp.ai"
        )
        return

    print(f"Fetching today's {sport.upper()} schedule...")
    schedule = ShippSchedule(api_key)
    if not schedule.connect(sport):
        print("Could not connect to schedule feed.")
        return

    try:
        games = schedule.get_today_games()
        if not games:
            print(f"No {sport.upper()} games found for today.")
            return

        print(f"Found {len(games)} games. Generating matchup cards...\n")

        for game in games:
            home = game.get("home_team") or game.get("home") or {}
            away = game.get("away_team") or game.get("away") or {}

            if isinstance(home, dict):
                home_name = (
                    home.get("name")
                    or home.get("full_name")
                    or home.get("abbreviation", "HOME")
                )
            else:
                home_name = str(home)

            if isinstance(away, dict):
                away_name = (
                    away.get("name")
                    or away.get("full_name")
                    or away.get("abbreviation", "AWAY")
                )
            else:
                away_name = str(away)

            if sport == "nba":
                card = build_nba_team_matchup(away_name, home_name)
            elif sport == "mlb":
                card = build_mlb_team_matchup(away_name, home_name)
            elif sport == "soccer":
                card = build_soccer_matchup(away_name, home_name, competition)
            else:
                card = f"Unsupported sport: {sport}"

            print(card)
            print()

    finally:
        schedule.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_edge(
    val_a: float,
    val_b: float,
    higher_is_better: bool,
    label_a: str,
    label_b: str,
) -> str:
    """Determine which side has the edge and how significant it is."""
    try:
        a = float(val_a)
        b = float(val_b)
    except (ValueError, TypeError):
        return ""

    if a == b:
        return "EVEN"

    diff = abs(a - b)
    mean = (abs(a) + abs(b)) / 2 if (abs(a) + abs(b)) > 0 else 1
    pct_diff = diff / mean * 100

    if (a > b) == higher_is_better:
        winner = label_a
    else:
        winner = label_b

    if pct_diff >= 15:
        return f"{winner}>>"
    elif pct_diff >= 5:
        return f"{winner}>"
    else:
        return f"~{winner}"


def _safe_float(value) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Matchup Analyzer — head-to-head sports breakdowns"
    )
    parser.add_argument(
        "--sport",
        type=str,
        choices=["nba", "mlb", "soccer"],
        required=True,
        help="Sport for analysis",
    )
    parser.add_argument(
        "--teams",
        type=str,
        default="",
        help="Two team names separated by comma (e.g. 'Lakers,Celtics')",
    )
    parser.add_argument(
        "--players",
        type=str,
        default="",
        help="Two player names separated by comma (NBA only)",
    )
    parser.add_argument(
        "--today",
        action="store_true",
        help="Generate matchup cards for all of today's games",
    )
    parser.add_argument(
        "--competition",
        type=str,
        default="premier_league",
        help="Soccer competition (default: premier_league). "
             "Options: premier_league, la_liga, bundesliga, serie_a, champions_league",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Validate input
    if not args.teams and not args.players and not args.today:
        parser.error(
            "Provide --teams, --players, or --today for analysis."
        )

    if args.today:
        preview_today(args.sport, args.competition)
        return

    if args.players:
        if args.sport != "nba":
            print("Player comparison currently supported for NBA only.")
            sys.exit(1)
        names = [n.strip() for n in args.players.split(",") if n.strip()]
        if len(names) != 2:
            parser.error("--players requires exactly two names separated by comma.")
        print(f"\nAnalyzing: {names[0]} vs {names[1]}\n")
        card = build_nba_player_matchup(names[0], names[1])
        print(card)
        return

    if args.teams:
        teams = [t.strip() for t in args.teams.split(",") if t.strip()]
        if len(teams) != 2:
            parser.error("--teams requires exactly two team names separated by comma.")

        print(f"\nAnalyzing: {teams[0]} vs {teams[1]}\n")

        if args.sport == "nba":
            card = build_nba_team_matchup(teams[0], teams[1])
        elif args.sport == "mlb":
            card = build_mlb_team_matchup(teams[0], teams[1])
        elif args.sport == "soccer":
            card = build_soccer_matchup(teams[0], teams[1], args.competition)
        else:
            card = f"Unsupported sport: {args.sport}"

        print(card)


if __name__ == "__main__":
    main()
