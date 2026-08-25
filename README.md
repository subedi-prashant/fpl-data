# fpl-data

A Python project that fetches and stores **Fantasy Premier League** data from the public FPL API — no authentication required.

## What it fetches

| Endpoint | Data |
|---|---|
| `/api/bootstrap-static/` | All players, teams, gameweeks, positions |
| `/api/fixtures/` | Full fixture list with difficulty ratings |
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
│   ├── client.py      # requests.Session + retry/backoff + cache-age check
│   ├── models.py      # dataclasses: Player, Team, Fixture, Gameweek, PlayerHistory
│   ├── storage.py     # raw JSON cache + SQLite upserts
│   └── cli.py         # typer CLI
└── tests/
    ├── conftest.py
    ├── test_client.py
    ├── test_models.py
    ├── test_storage.py
    └── test_cli.py
```

---

## Dashboard

Run the Streamlit dashboard locally:

```bash
streamlit run dashboard/app.py
```

Opens at **http://localhost:8501** with 5 pages:

| Page | What it shows |
|---|---|
| 🏠 Overview | Key stats + top 10 + points by position |
| 📊 Player Explorer | Filterable table (position, price, status, sort) |
| 💎 Best Value | Top players by points-per-£1m |
| 🔥 Form Table | Sorted by current form / points-per-game |
| 📅 Fixture Difficulty | Colour-coded team × gameweek heatmap |

The dashboard works in two modes:
- **Local** (after `fpl-data fetch-all`): reads from `data/fpl.db` instantly
- **Cloud / no DB**: fetches live from the FPL API, cached 6 hours

---

## Deploy to Streamlit Community Cloud (free)

1. **Push this repo to GitHub** (must be public for the free tier):
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   gh repo create my-fpl --public --source=. --push
   ```

2. Go to **[share.streamlit.io](https://share.streamlit.io)** → sign in with GitHub → **New app**

3. Fill in:
   - **Repository**: `your-username/my-fpl`
   - **Branch**: `main`
   - **Main file path**: `fpl-data/dashboard/app.py`

4. Click **Deploy** — Streamlit Cloud installs from `requirements.txt` automatically.

The deployed app fetches live FPL data directly (no database hosting needed).

---

## Notes

- **Polite client**: requests include a descriptive `User-Agent` header and sleep 0.3 s between individual player-summary calls to avoid hammering the FPL servers.
- **Read-only**: this phase only uses public, unauthenticated endpoints.
- The `data/` directory is gitignored. Create it by running any fetch command.
