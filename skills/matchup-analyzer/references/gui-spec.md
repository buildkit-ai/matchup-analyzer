# GUI Specification: matchup-analyzer

## Design Direction
- **Style:** Side-by-side comparison layout with a dark cosmic theme. Symmetrical two-column design with shared statistical axes between columns. Data visualizations (radar charts, stat bars) are central to the experience, turning raw numbers into immediate visual understanding.
- **Inspiration:** UFC/boxing tale-of-the-tape comparison graphics, FiveThirtyEight matchup prediction pages on Dribbble, Nike sports comparison UI concepts on Behance
- **Mood:** Competitive, analytical, balanced, dynamic

## Layout
- **Primary view:** Symmetric three-section layout. Left column (35%) for Team/Player A with logo, name, record, and stat values. Center column (30%) for comparison visualizations — horizontal stat bars meeting in the middle, radar/spider chart, and win probability gauge. Right column (35%) mirrors left for Team/Player B. Top section (80px) has matchup title, date, and venue.
- **Mobile:** Stacks vertically. Team A card on top, comparison chart in middle (radar chart becomes horizontal bar chart), Team B card below. Swipeable tabs for different stat categories.
- **Header:** Matchup title bar with: Team A logo + name (left), "VS" divider with game date/time (center), Team B logo + name (right). Background subtly blends team colors from left and right edges.

## Color Palette
- Background: #1A1A2E (Cosmic Navy)
- Surface: #16213E (Deep Indigo Panel)
- Primary accent: #F59E0B (Highlight Amber) — key differentiators, winning stat highlights, hover states
- Success: #34D399 (Advantage Green) — stat leader indicators, positive trends
- Warning: #EF4444 (Deficit Red) — weaker side indicators, negative trends
- Text primary: #E2E8F0 (Soft White)
- Text secondary: #94A3B8 (Muted Slate)

## Component Structure
- **TeamHeader** — Team/player identity block with logo, full name, record (W-L), conference/division, and optional ranking badge. Dynamic border-bottom color matches team primary color.
- **ComparisonBar** — Horizontal bar chart where two bars grow from center outward (left for Team A, right for Team B). The longer bar is highlighted in amber. Stat label and values sit at each end.
- **RadarChart** — Spider/radar chart overlaying both teams' stat profiles. Team A in their primary color (semi-transparent fill), Team B in theirs. Axes: offense, defense, pace, efficiency, rebounding/possession, clutch.
- **WinProbabilityGauge** — Horizontal split bar showing predicted win percentage for each team. Team colors fill from each side. Percentage labels on each half.
- **TrendArrow** — Small inline indicator showing recent form. Green up-arrow for improving, red down-arrow for declining, grey dash for stable. Appears next to key stats.
- **HeadToHeadHistory** — Compact table showing last 5-10 matchups between these teams with date, score, and winner highlighted. Scrollable on overflow.
- **StatCategoryTabs** — Tab bar to switch between stat categories: Overview, Offense, Defense, Advanced, Recent Form. Active tab underlined in amber.

## Typography
- Headings: Inter Bold, 20-28px, letter-spacing -0.02em, #E2E8F0
- Body: Inter Regular, 14-16px, line-height 1.5, #94A3B8 for secondary, #E2E8F0 for primary
- Stats/numbers: JetBrains Mono Bold, 24-36px for headline stats, 14-16px for comparison values, tabular-nums enabled

## Key Interactions
- **Team swap:** Clicking a swap icon between the team headers animates both columns sliding past each other (300ms ease-in-out) to reverse positions.
- **Stat bar hover:** Hovering over a comparison bar expands it slightly (scale-y 1.1), reveals exact values, difference delta, and league rank in a tooltip.
- **Radar chart toggle:** Clicking a radar axis label toggles that stat dimension on/off, allowing users to focus on specific comparison areas. Toggled-off axes fade to 20% opacity.
- **Category tab switch:** Switching stat categories cross-fades the comparison bars and radar chart data with a 250ms transition. Bars animate from zero to their values.
- **Head-to-head row hover:** Hovering a historical matchup row highlights it in amber and shows a mini box-score tooltip.
- **Team color theming:** When teams are selected/changed, the header gradient and chart colors transition to match the new teams' primary colors over 400ms.

## Reference Screenshots
- [UFC Tale of the Tape Comparison on Dribbble](https://dribbble.com/search/versus-comparison-sports) — Symmetric side-by-side layout with stat bars meeting in the center
- [FiveThirtyEight Game Prediction on Behance](https://www.behance.net/search/projects?search=sports+matchup+comparison) — Data visualization-forward comparison with win probability and radar charts
- [Nike Sports Comparison Concept on Mobbin](https://mobbin.com/search/sports-comparison) — Clean dark theme head-to-head layout with dynamic team color theming
