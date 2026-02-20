# Matchup Analyzer

**Data-driven matchup breakdowns.** Head-to-head team and player comparisons with stats, trends, and key factors for NBA, MLB, and Soccer.

---

## The Problem

You want to break down tonight's Lakers vs Celtics game, but the stats are scattered across five different sites. You need offensive vs defensive ratings, key player matchups, recent form, and head-to-head history -- all in one clean view.

## The Solution

Matchup Analyzer pulls from multiple data sources to produce a single, structured matchup card. It compares teams across every meaningful stat category, flags the key advantage areas, and highlights players to watch.

```
+------------------------------------------------------+
|              MATCHUP CARD -- NBA                     |
|         Lakers (32-20) vs Celtics (38-14)            |
|         Feb 18, 2026  |  TD Garden  |  7:30 PM ET   |
+------------------------------------------------------+
|                                                      |
|  TEAM COMPARISON                                     |
|  ┌────────────────────────────────────────────┐      |
|  │ Category        LAL         BOS    Edge    │      |
|  │ ──────────────────────────────────────────  │      |
|  │ PPG             112.4      118.7   BOS>>   │      |
|  │ Opp PPG         108.1      104.2   BOS>    │      |
|  │ FG%             .478       .491    BOS>    │      |
|  │ 3PT%            .364       .389    BOS>>   │      |
|  │ REB/G           44.2       45.8    BOS>    │      |
|  │ AST/G           27.1       26.8    LAL>    │      |
|  │ TOV/G           13.8       12.1    BOS>    │      |
|  │ Last 10         7-3        8-2     BOS>    │      |
|  └────────────────────────────────────────────┘      |
|                                                      |
|  KEY MATCHUP                                         |
|  LeBron James vs Jayson Tatum                        |
|  LBJ: 25.8/7.4/7.1  |  JT: 27.2/8.3/4.8           |
|  Edge: Tatum scoring, LeBron playmaking              |
|                                                      |
|  EDGE FACTORS                                        |
|  + BOS: Home court, top-5 defense, 3PT shooting     |
|  + LAL: LeBron playoff mode, strong recent form     |
|  ~ Both teams healthy, no major injuries             |
+------------------------------------------------------+
```

## Features

- **Multi-sport** — NBA, MLB, and Soccer matchup analysis
- **Team vs team** — Full statistical comparison with edge indicators
- **Player vs player** — Direct stat-line comparisons
- **Game previews** — Auto-generates cards for today's scheduled games
- **Trend detection** — Recent form analysis (last 5/10 games)
- **Markdown output** — Clean, structured reports ready to share
- **Live context** — Integrates current game state for in-progress matchups

## Quick Start

### 1. Install dependencies

```bash
pip install requests
```

### 2. Set your API keys

Requires a Shipp.ai API key for schedule and live game data -- get 5,000 free credits/day at [platform.shipp.ai](https://platform.shipp.ai).

```bash
export SHIPP_API_KEY="your-api-key-here"

# Optional: for soccer matchups (free at football-data.org)
export FOOTBALL_DATA_API_KEY="your-key-here"
```

### 3. Run matchup analysis

```bash
# NBA team matchup
python scripts/analyzer.py --sport nba --teams "Lakers,Celtics"

# MLB pitcher matchup
python scripts/analyzer.py --sport mlb --teams "Yankees,Red Sox"

# Soccer match preview
python scripts/analyzer.py --sport soccer --teams "Arsenal,Bayern Munich"

# Player vs player comparison
python scripts/analyzer.py --sport nba --players "LeBron James,Jayson Tatum"

# Auto-preview all of today's games
python scripts/analyzer.py --sport nba --today
```

## Analysis Types

### Team vs Team
Compares two teams across offensive and defensive categories. Identifies which team has the statistical edge in each area and calls out the most significant advantages.

### Player vs Player
Direct comparison of two players' season stats. Useful for fantasy decisions, debate settling, and understanding individual matchups within a game.

### Game Preview (--today)
Automatically generates matchup cards for every game on today's schedule. Ideal for morning prep or pre-game analysis.

## Data Sources

| Source | Data | Auth Required |
|--------|------|---------------|
| Live game feed (via Shipp.ai) | Today's schedule, live scores | API key (free tier) |
| balldontlie.io | NBA team/player stats | None |
| statsapi.mlb.com | MLB team stats, pitcher/batter splits | None |
| football-data.org | Soccer standings, head-to-head records | API key (free tier) |

## Configuration

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `SHIPP_API_KEY`     | Yes      | API key for schedule and live data |
| `FOOTBALL_DATA_API_KEY` | No  | football-data.org key for soccer data |

## License

MIT

---

<sub>Powered by [Shipp.ai](https://shipp.ai) real-time sports data</sub>
