# fpl-data

[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-myfpldata.streamlit.app-FF4B4B?logo=streamlit)](https://myfpldata.streamlit.app/)

A Python project that fetches and stores **Fantasy Premier League** data from the public FPL API — no authentication required.

🚀 **Live app**: [myfpldata.streamlit.app](https://myfpldata.streamlit.app/)

## What it fetches

| Endpoint | Data |
|---|---|
| `/api/bootstrap-static/` | All players, teams, gameweeks, positions, scoring rules, injury news |
| `/api/fixtures/` | Full fixture list with difficulty ratings |
| `/api/event/{gw}/live/` | Every player's stats for one gameweek (xG, xA, minutes, defensive actions) |
| `/api/element-summary/{player_id}/` | Per-player gameweek history |

Data is saved to:
- `data/raw/` — timestamped raw JSON responses  
- `data/fpl.db` — SQLite database with tables: `players`, `teams`, `fixtures`, `gameweeks`, `player_history`

---

## Setup

### 1. Create and activate a virtual environment

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install the package

```bash
pip install -e ".[dev]"
```

---

## CLI Usage

Run commands via the `fpl-data` entry point (or `python -m fpl_data.cli`).

### Fetch everything (players + fixtures + all player histories)

```bash
fpl-data fetch-all
```

Options:
- `--cache-ttl FLOAT` — Bootstrap cache TTL in hours (default `6`). Skips re-fetching bootstrap-static if the local cache is newer than this.
- `--verbose / -v` — Enable DEBUG logging.
- `--data-dir PATH` — Root directory for `raw/` and `fpl.db` (default `data/`).

### Fetch only players, teams, and gameweeks

```bash
fpl-data fetch-players
```

### Fetch only fixtures

```bash
fpl-data fetch-fixtures
```

### Force re-fetch everything (ignore cache)

```bash
fpl-data refresh
# or use a zero TTL explicitly:
fpl-data refresh --cache-ttl 0
```

### Backtest the projection model

```bash
fpl-data backtest --from-gw 4
```

Walk-forward test on this season's finished gameweeks: each gameweek is predicted using only data from before it, then scored against actual points. Prints RMSE, MAE, rank correlation and the points scored by each model's top 20 picks, for the xP model and the previous form/PPG formula.

---

## Running tests

```bash
pytest
# with coverage:
pytest --cov=fpl_data --cov-report=term-missing
```

Tests use `responses` to mock all HTTP — no real API calls are made during testing.

---

## Project structure

```
fpl-data/
├── pyproject.toml
├── README.md
├── fpl_data/
│   ├── __init__.py
│   ├── client.py           # requests.Session + retry/backoff + cache-age check
│   ├── models.py           # dataclasses: Player, Team, Fixture, Gameweek, PlayerHistory
│   ├── storage.py          # raw JSON cache + SQLite upserts
│   ├── frames.py           # API payloads -> tidy pandas DataFrames
│   ├── projections.py      # expected-points model (team model, minutes, injuries, scoring)
│   ├── recommendations.py  # sale prices, squad rules, transfer planner, free transfers
│   ├── backtest.py         # walk-forward model evaluation
│   └── cli.py              # typer CLI
├── dashboard/
│   ├── app.py              # entrypoint: sidebar + st.navigation
│   ├── data.py             # cached live-API loading
│   ├── ui.py               # shared page helpers
│   ├── components.py       # pitch, badges, move explanations (pure functions)
│   └── app_pages/          # planner, team, review, players, fixtures, injuries
└── tests/
```

---

## How transfer recommendations work

Recommendations come from an **expected points (xP)** model built per fixture, following the component approach used by public FPL models such as [AIrsenal](https://github.com/alan-turing-institute/AIrsenal) and the open-source FPL optimisation tools:

| Component | What it uses |
|---|---|
| **Fixtures** | Poisson team model: attack and defence ratings plus home advantage, fitted on this season's results (70% xG, 30% goals), time-decayed and regularised toward FPL's team strengths. Gives expected goals for/against per match, clean-sheet odds and a 1–5 difficulty. Blank and double gameweeks are handled per fixture. |
| **Form** | Per-90 xG, xA, saves, defensive actions, bonus and cards from `/event/{gw}/live/`, weighted toward recent gameweeks (4 GW half-life) and shrunk toward a price-based positional prior (450 pseudo-minutes). |
| **Minutes** | Start probability, minutes when starting and the 60-minute rate from recent appearances (3 GW half-life), so rotation risks score lower. |
| **Injuries** | FPL status and chance of playing, plus return dates parsed from the news ("Expected back 21 Nov", "Suspended until 29 Nov") and loan restrictions. Doubtful players recover over the following weeks; injured players score zero until their return. |
| **Scoring** | Current rules read from `game_config.scoring` (appearance, goals, assists, clean sheets, goals conceded, saves, defensive contributions at 10 CBIT / 12 CBIRT, bonus, cards). |

The planner then scores every legal one- or two-transfer move: best XI each gameweek with the captain counted twice, a small bench weighting (0.03 / 0.21 / 0.06 / 0.002), nearer gameweeks weighted more (×0.84 per week), −4 per hit, and a move must beat the value of saving a free transfer (1.5 pts). Free transfers are rebuilt from your public history (max five, kept on Wildcard/Free Hit).

In a walk-forward backtest on GW4–8 of 2026/27 (no injury data available historically, so this understates the real gain), the xP model reduced RMSE from 2.94 to 2.74 points per player-gameweek, raised rank correlation from 0.42 to 0.48, and its top 20 picks scored 82.6 points per gameweek against 76.0 for the previous formula. Rerun it any time with `fpl-data backtest`.

---

## Dashboard

Run the Streamlit dashboard locally:

```bash
streamlit run dashboard/app.py
```

Opens at **http://localhost:8501**. Enter your public manager ID in the sidebar (or set `FPL_MANAGER_ID` in `.env`). The ID is kept in the URL, so `http://localhost:8501/?manager=1234567` links straight to your team.

| Page | What it shows |
|---|---|
| Transfer planner | Recommended move (or "roll the transfer"), why it's recommended, alternatives, flagged players in your squad and your squad's xP per gameweek |
| My team | Pitch view with next fixture and xP per player, suggested captain, sale prices |
| Decision review | Points per gameweek vs the FPL average, hits, bench points and transfer history |
| Players | Every player ranked by projected points, with fixtures, last 5 gameweeks and expected minutes |
| Fixtures | Team × gameweek ticker coloured by model difficulty, with attack (xG) and defence (clean-sheet %) views |
| Injuries & news | All flagged players with expected return date and projected points impact |

The dashboard always reads live public FPL data (cached for 15 minutes), so it needs no database. The CLI and `data/fpl.db` remain available for offline analysis.

---

## Deploy to Streamlit Community Cloud (free)

> ✅ Already deployed at **[myfpldata.streamlit.app](https://myfpldata.streamlit.app/)**

To deploy your own fork:

1. Fork this repo and go to **[share.streamlit.io](https://share.streamlit.io)** → sign in with GitHub → **New app**

2. Fill in:
   - **Repository**: `your-username/fpl-data`
   - **Branch**: `master`
   - **Main file path**: `dashboard/app.py`

3. Click **Deploy** — Streamlit Cloud installs from `requirements.txt` automatically.

The deployed app fetches live FPL data directly (no database hosting needed).

---

## Notes

- **Polite client**: requests include a descriptive `User-Agent` header and sleep 0.3 s between individual player-summary calls to avoid hammering the FPL servers.
- **Read-only**: this phase only uses public, unauthenticated endpoints.
- The `data/` directory is gitignored. Create it by running any fetch command.
