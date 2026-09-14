"""
FPL Dashboard — Streamlit app.

Works in two modes:
  • Local: reads from data/fpl.db (run `fpl-data fetch-all` first)
  • Cloud: fetches directly from the public FPL API (no DB needed)
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard.components import formation_label, render_pitch
from fpl_data.recommendations import (
    calculate_selling_price,
    infer_purchase_prices,
    recommend_transfers,
    validate_squad,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="My FPL · Transfer planner",
    page_icon=":material/sports_soccer:",
    layout="wide",
    initial_sidebar_state="expanded",
)

_DB_PATH = _ROOT / "data" / "fpl.db"
_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_STATUS_LABEL = {"a": "Available", "d": "Doubtful", "i": "Injured", "u": "Unavailable", "s": "Suspended"}

# ---------------------------------------------------------------------------
# Custom CSS — tighten spacing and style section headers
# ---------------------------------------------------------------------------

st.html("""
<style>
.st-key-sidebar-brand { padding: .25rem 0 .6rem; }
.st-key-sidebar-brand p { margin: 0; color: rgba(255,255,255,.7); }
.st-key-manager-summary { padding: .15rem 0; }
.st-key-primary-recommendation { border-left: 4px solid #008a55; }
</style>
""")

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=15 * 60, show_spinner="Fetching FPL data…")
def _fetch_bootstrap() -> dict:
    r = requests.get(
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=15 * 60, show_spinner="Fetching fixtures…")
def _fetch_fixtures() -> list[dict]:
    r = requests.get(
        "https://fantasy.premierleague.com/api/fixtures/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=15 * 60, max_entries=100, show_spinner=False)
def _fetch_manager_profile(manager_id: int) -> dict:
    response = requests.get(
        f"https://fantasy.premierleague.com/api/entry/{manager_id}/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15 * 60, max_entries=100, show_spinner=False)
def _fetch_manager_picks(manager_id: int, gameweek: int) -> dict:
    response = requests.get(
        f"https://fantasy.premierleague.com/api/entry/{manager_id}/event/{gameweek}/picks/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15 * 60, max_entries=100, show_spinner=False)
def _fetch_manager_transfers(manager_id: int) -> list[dict]:
    response = requests.get(
        f"https://fantasy.premierleague.com/api/entry/{manager_id}/transfers/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15 * 60, max_entries=100, show_spinner=False)
def _fetch_manager_history(manager_id: int) -> dict:
    response = requests.get(
        f"https://fantasy.premierleague.com/api/entry/{manager_id}/history/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _build_players_df(bootstrap: dict) -> pd.DataFrame:
    teams = {t["id"]: t for t in bootstrap["teams"]}
    rows = []
    for p in bootstrap["elements"]:
        t = teams.get(p["team"], {})
        rows.append({
            "id": p["id"],
            "web_name": p["web_name"],
            "team_id": p["team"],
            "team": t.get("name", ""),
            "team_short": t.get("short_name", ""),
            "position": _POSITION_MAP.get(p["element_type"], "?"),
            "element_type": p["element_type"],
            "now_cost": p["now_cost"],
            "cost_change_start": p.get("cost_change_start", 0),
            "cost_m": p["now_cost"] / 10.0,
            "total_points": p["total_points"],
            "event_points": p.get("event_points", 0),
            "minutes": p.get("minutes", 0),
            "goals_scored": p.get("goals_scored", 0),
            "assists": p.get("assists", 0),
            "clean_sheets": p.get("clean_sheets", 0),
            "selected_pct": float(p.get("selected_by_percent", 0)),
            "form": float(p.get("form", 0)),
            "ppg": float(p.get("points_per_game", 0)),
            "ep_next": float(p.get("ep_next") or 0),
            "status": p.get("status", "a"),
            "chance_of_playing": p.get("chance_of_playing_next_round"),
            "news": p.get("news", ""),
        })
    df = pd.DataFrame(rows)
    df["value"] = (df["total_points"] / df["cost_m"]).round(1)
    return df


def _build_fixtures_df(raw: list[dict], teams: dict) -> pd.DataFrame:
    rows = []
    for f in raw:
        th = teams.get(f["team_h"], {})
        ta = teams.get(f["team_a"], {})
        rows.append({
            "event": f.get("event"),
            "gw": f.get("event"),
            "team_h_id": f["team_h"],
            "team_h": th.get("name", ""),
            "team_h_short": th.get("short_name", ""),
            "team_a_id": f["team_a"],
            "team_a": ta.get("name", ""),
            "team_a_short": ta.get("short_name", ""),
            "team_h_difficulty": f.get("team_h_difficulty", 0),
            "team_a_difficulty": f.get("team_a_difficulty", 0),
            "team_h_score": f.get("team_h_score"),
            "team_a_score": f.get("team_a_score"),
            "finished": bool(f.get("finished", False)),
        })
    return pd.DataFrame(rows)


def _build_heatmap(fixtures_df: pd.DataFrame, current_gw: int, next_n: int) -> pd.DataFrame:
    gw_range = list(range(current_gw, current_gw + next_n))
    upcoming = fixtures_df[fixtures_df["gw"].isin(gw_range)].copy()
    home = upcoming[["gw", "team_h_short", "team_a_short", "team_h_difficulty"]].copy()
    home.columns = ["gw", "team", "opponent", "difficulty"]
    home["venue"] = "H"
    away = upcoming[["gw", "team_a_short", "team_h_short", "team_a_difficulty"]].copy()
    away.columns = ["gw", "team", "opponent", "difficulty"]
    away["venue"] = "A"
    combined = pd.concat([home, away], ignore_index=True)
    combined["label"] = combined["opponent"] + "(" + combined["venue"] + ")"
    pivot = combined.pivot_table(index="team", columns="gw", values="difficulty", aggfunc="first")
    pivot.columns = [f"GW{c}" for c in pivot.columns]
    return pivot.reset_index().rename(columns={"team": "Team"})


# ---------------------------------------------------------------------------
# Load public data (DB or live API)
# ---------------------------------------------------------------------------

_USE_DB = _DB_PATH.exists()

if _USE_DB:
    from fpl_data.storage import migrate_db
    migrate_db(_DB_PATH)

if _USE_DB:
    @st.cache_data(ttl=6 * 3600)
    def get_players_df() -> pd.DataFrame:
        from fpl_data.analysis import load_players
        return load_players(_DB_PATH).rename(columns={"points_per_game": "ppg", "selected_by_percent": "selected_pct"})

    @st.cache_data(ttl=6 * 3600)
    def get_fixtures_df() -> pd.DataFrame:
        from fpl_data.analysis import load_fixtures
        return load_fixtures(_DB_PATH).rename(columns={"event": "gw"})

    @st.cache_data(ttl=6 * 3600)
    def get_gameweeks_df() -> pd.DataFrame:
        from fpl_data.analysis import load_gameweeks
        return load_gameweeks(_DB_PATH)

    def get_current_gw(gws_df: pd.DataFrame) -> int:
        cur = gws_df[gws_df["is_current"] == 1]["id"]
        return int(cur.iloc[0]) if not cur.empty else 1
else:
    @st.cache_data(ttl=6 * 3600, show_spinner="Fetching FPL data…")
    def get_players_df() -> pd.DataFrame:
        return _build_players_df(_fetch_bootstrap())

    @st.cache_data(ttl=6 * 3600, show_spinner="Fetching fixtures…")
    def get_fixtures_df() -> pd.DataFrame:
        bootstrap = _fetch_bootstrap()
        teams = {t["id"]: t for t in bootstrap["teams"]}
        return _build_fixtures_df(_fetch_fixtures(), teams)

    @st.cache_data(ttl=6 * 3600)
    def get_gameweeks_df() -> pd.DataFrame:
        return pd.DataFrame(_fetch_bootstrap()["events"])

    def get_current_gw(gws_df: pd.DataFrame) -> int:
        cur = gws_df[gws_df["is_current"] == True]["id"]
        return int(cur.iloc[0]) if not cur.empty else 1


# ---------------------------------------------------------------------------
# Manager data helpers (only when DB is available)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=15 * 60, max_entries=100)
def _get_manager_profile(mid: int) -> dict | None:
    raw_profile = _fetch_manager_profile(mid)
    manager_name = f"{raw_profile.get('player_first_name', '')} {raw_profile.get('player_last_name', '')}".strip()
    return {
        "manager_id": mid,
        "name": manager_name,
        "team_name": raw_profile.get("name", "Unnamed team"),
        "team_value": raw_profile.get("last_deadline_value", 0) / 10,
        "bank": raw_profile.get("last_deadline_bank", 0) / 10,
        "bank_units": int(raw_profile.get("last_deadline_bank", 0)),
        "total_points": int(raw_profile.get("summary_overall_points", 0)),
        "event_points": int(raw_profile.get("summary_event_points", 0)),
        "rank": raw_profile.get("summary_overall_rank"),
        "current_event": int(raw_profile.get("current_event") or 0),
    }


def _default_manager_id() -> int:
    env_manager_id = os.getenv("FPL_MANAGER_ID", "").strip()
    if env_manager_id.isdigit():
        return int(env_manager_id)
    for db_path in [_DB_PATH, _ROOT.parent / "data" / "fpl.db"]:
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(str(db_path)) as connection:
                row = connection.execute("SELECT manager_id FROM user_profile ORDER BY manager_id LIMIT 1").fetchone()
            if row:
                return int(row[0])
        except sqlite3.Error:
            continue
    return 0


def _build_manager_squad(
    players: pd.DataFrame,
    picks_payload: dict,
    transfers: list[dict],
    history_payload: dict,
) -> pd.DataFrame:
    picks = pd.DataFrame(picks_payload.get("picks", []))
    if picks.empty:
        return picks
    picks = picks.rename(columns={"element": "id", "position": "squad_pos"})
    picks = picks[["id", "squad_pos", "is_captain", "is_vice_captain", "multiplier"]]
    squad = picks.merge(players, on="id", how="left", validate="one_to_one")
    ignored_events = {
        int(chip["event"])
        for chip in history_payload.get("chips", [])
        if chip.get("name") == "freehit"
    }
    purchase_prices = infer_purchase_prices(squad["id"], players, transfers, ignored_events)
    squad["purchase_cost"] = squad["id"].map(purchase_prices).astype(int)
    squad["selling_price"] = squad.apply(
        lambda player: calculate_selling_price(player["now_cost"], player["purchase_cost"]),
        axis=1,
    )
    return squad.sort_values("squad_pos").reset_index(drop=True)


def _next_gameweek(gameweeks: pd.DataFrame, current_gameweek: int) -> int:
    next_rows = gameweeks[gameweeks["is_next"] == True]
    if not next_rows.empty:
        return int(next_rows.iloc[0]["id"])
    return min(38, current_gameweek + 1)


def _fixture_run(fixtures: pd.DataFrame, team_id: int, first_gameweek: int, horizon: int) -> str:
    labels = []
    for gameweek in range(first_gameweek, first_gameweek + horizon):
        home = fixtures[(fixtures["gw"] == gameweek) & (fixtures["team_h_id"] == team_id)]
        away = fixtures[(fixtures["gw"] == gameweek) & (fixtures["team_a_id"] == team_id)]
        gameweek_labels = [f"{row['team_a_short']} (H)" for _, row in home.iterrows()]
        gameweek_labels.extend(f"{row['team_h_short']} (A)" for _, row in away.iterrows())
        labels.append(" + ".join(gameweek_labels) if gameweek_labels else "—")
    return " · ".join(labels)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar.container(key="sidebar-brand"):
    st.title("My FPL")
    st.caption("Your squad. Your budget. Better transfers.")

# ── League Data ──────────────────────────────────────────────────────────────
st.session_state.setdefault("manager_id", _default_manager_id())
with st.sidebar.form("manager_lookup", border=False):
    raw_mid = st.text_input(
        "Manager ID",
        value=str(st.session_state.manager_id or ""),
        placeholder="e.g. 7540623",
        help="Find the number in your public FPL team URL.",
    )
    submitted_manager = st.form_submit_button(
        "Load team",
        icon=":material/download:",
        type="primary",
        width="stretch",
    )
if submitted_manager:
    st.session_state.manager_id = int(raw_mid) if raw_mid.strip().isdigit() else 0
manager_id = int(st.session_state.manager_id or 0)
has_manager = manager_id > 0

# ── My FPL ───────────────────────────────────────────────────────────────────
manager_profile: dict | None = None
season: int | None = None
if has_manager:
    try:
        manager_profile = _get_manager_profile(manager_id)
    except requests.RequestException:
        manager_profile = None

if manager_profile:
    # Inline status chip
    rank_str = f"#{manager_profile['rank']:,}" if manager_profile["rank"] else "Unranked"
    with st.sidebar.container(border=True, key="manager-summary"):
        st.markdown(f"**{manager_profile['team_name']}**")
        st.caption(f"{manager_profile['name']} · {rank_str}")
elif has_manager:
    st.sidebar.error("That public manager ID could not be loaded.", icon=":material/error:")

workspace = st.sidebar.radio(
    "Navigation",
    ["Recommendations", "My Season", "My Decisions", "League Data"],
    format_func=lambda page: {
        "Recommendations": ":material/swap_horiz: Transfer planner",
        "My Season": ":material/groups: My team",
        "My Decisions": ":material/query_stats: Decision review",
        "League Data": ":material/table_chart: League data",
    }[page],
)
personal_page = workspace if workspace != "League Data" else None

if workspace == "League Data":
    league_page = st.sidebar.radio(
        "League view",
        ["Overview", "Player Explorer", "Best Value", "Form Table", "Fixture Difficulty"],
    )
else:
    league_page = "Overview"

# Determine active section: personal pages take over when selected
active_section = "league" if workspace == "League Data" else "personal" if manager_profile else "setup"

if st.sidebar.button("Refresh data", icon=":material/refresh:", width="stretch"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("Public FPL data · cached for 15 minutes")

# ---------------------------------------------------------------------------
# Load public data
# ---------------------------------------------------------------------------

if active_section == "personal":
    live_bootstrap = _fetch_bootstrap()
    live_teams = {team["id"]: team for team in live_bootstrap["teams"]}
    players_df = _build_players_df(live_bootstrap)
    fixtures_df = _build_fixtures_df(_fetch_fixtures(), live_teams)
    gameweeks_df = pd.DataFrame(live_bootstrap["events"])
else:
    players_df = get_players_df()
    fixtures_df = get_fixtures_df()
    gameweeks_df = get_gameweeks_df()
current_gw = get_current_gw(gameweeks_df)
next_gw = _next_gameweek(gameweeks_df, current_gw)
season = int(str(gameweeks_df.iloc[0]["deadline_time"])[:4]) if not gameweeks_df.empty else None
manager_gameweek = (manager_profile["current_event"] or current_gw) if manager_profile else current_gw
manager_picks: dict = {}
manager_history: dict = {}
manager_transfers: list[dict] = []
manager_squad = pd.DataFrame()
squad_error = ""
if active_section == "personal" and manager_profile:
    try:
        manager_picks = _fetch_manager_picks(manager_id, manager_gameweek)
        manager_history = _fetch_manager_history(manager_id)
        manager_transfers = _fetch_manager_transfers(manager_id)
        manager_squad = _build_manager_squad(players_df, manager_picks, manager_transfers, manager_history)
        manager_squad["next_fixture"] = manager_squad["team_id"].map(
            lambda team_id: _fixture_run(fixtures_df, int(team_id), next_gw, 1)
        )
        entry_history = manager_picks.get("entry_history", {})
        manager_profile["bank_units"] = int(entry_history.get("bank", manager_profile["bank_units"]))
        manager_profile["bank"] = manager_profile["bank_units"] / 10
        manager_profile["event_points"] = int(entry_history.get("points", manager_profile["event_points"]))
    except (requests.RequestException, KeyError, ValueError) as error:
        squad_error = str(error)


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------

def _manager_banner(profile: dict, gw: int) -> None:
    """Sticky profile strip shown at the top of every personal page."""
    st.title(profile["team_name"])
    st.caption(f"{profile['name']} · Gameweek {gw}: {profile['event_points']} pts · {profile['total_points']:,} total points")
    rank_disp = f"{profile['rank']:,}" if profile["rank"] else "—"
    with st.container(horizontal=True):
        st.metric("Overall rank", rank_disp, border=True)
        st.metric("Team value", f"£{profile['team_value']:.1f}m", border=True)
        st.metric("In the bank", f"£{profile['bank']:.1f}m", border=True)


def _status_badge(s: str) -> str:
    return _STATUS_LABEL.get(s, s)


# ---------------------------------------------------------------------------
# ══ LEAGUE PAGES ════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

if active_section == "setup":
    st.title("Make the next transfer count")
    st.write("Enter your public FPL manager ID in the sidebar to load your current squad and budget.")
    st.info("No FPL login is required. Only public team data is read.", icon=":material/lock_open:")
    with st.container(border=True):
        st.subheader("Built for transfer decisions")
        st.markdown("- Uses the outgoing player's **actual FPL sale value**, not market price\n- Adds your current **money in the bank**\n- Preserves position quotas and the **three-player club limit**\n- Ranks affordable replacements over the upcoming fixtures")

elif active_section == "league":

    # ── Overview ─────────────────────────────────────────────────────────────
    if league_page == "Overview":
        st.title("FPL dashboard")
        st.caption(f"{season}/{str(season + 1)[-2:]} Premier League · Gameweek {current_gw}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Players", f"{len(players_df):,}", border=True)
        c2.metric("Teams", players_df["team"].nunique(), border=True)
        c3.metric("Fixtures", f"{len(fixtures_df):,}", border=True)
        c4.metric("Current GW", current_gw, border=True)

        col_l, col_r = st.columns([3, 2])
        with col_l:
            st.subheader("Top players by total points")
            top10 = (
                players_df.sort_values("total_points", ascending=False)
                .head(10)[["web_name", "team", "position", "cost_m", "total_points", "form", "value"]]
                .reset_index(drop=True)
            )
            top10.index += 1
            st.dataframe(
                top10,
                width="stretch",
                column_config={
                    "web_name": st.column_config.TextColumn("Player"),
                    "team": st.column_config.TextColumn("Team"),
                    "position": st.column_config.TextColumn("Pos", width="small"),
                    "cost_m": st.column_config.NumberColumn("Cost", format="£%.1fm"),
                    "total_points": st.column_config.NumberColumn("Pts"),
                    "form": st.column_config.NumberColumn("Form", format="%.1f"),
                    "value": st.column_config.NumberColumn("Value", format="%.1f", help="Points per £1m"),
                },
            )

        with col_r:
            st.subheader("Average points by position")
            pos_stats = (
                players_df.groupby("position")["total_points"].mean().round(1).reset_index()
            )
            pos_stats.columns = ["Position", "Avg Points"]
            st.bar_chart(pos_stats, x="Position", y="Avg Points")

    # ── Player Explorer ───────────────────────────────────────────────────────
    elif league_page == "Player Explorer":
        st.title("Player explorer")

        f1, f2, f3, f4 = st.columns(4)
        with f1:
            pos_filter = st.multiselect(
                "Position", ["GKP", "DEF", "MID", "FWD"],
                default=["GKP", "DEF", "MID", "FWD"],
            )
        with f2:
            price_max = st.slider("Max price (£m)", 4.0, 15.0, 15.0, 0.5)
        with f3:
            status_filter = st.multiselect(
                "Availability", list(_STATUS_LABEL.keys()),
                default=["a"],
                format_func=lambda s: _STATUS_LABEL.get(s, s),
            )
        with f4:
            sort_col = st.selectbox(
                "Sort by",
                ["total_points", "form", "ppg", "value", "cost_m", "goals_scored", "assists"],
                format_func=lambda c: {
                    "total_points": "Total Points", "form": "Form", "ppg": "Pts/Game",
                    "value": "Value", "cost_m": "Cost", "goals_scored": "Goals", "assists": "Assists",
                }[c],
            )

        filtered = players_df[
            players_df["position"].isin(pos_filter)
            & (players_df["cost_m"] <= price_max)
            & players_df["status"].isin(status_filter)
        ].sort_values(sort_col, ascending=False).reset_index(drop=True)

        st.caption(f"{len(filtered)} players")
        st.dataframe(
            filtered[["web_name", "team", "position", "cost_m", "total_points", "form", "ppg", "goals_scored", "assists", "clean_sheets", "value", "selected_pct", "status"]],
            width="stretch",
            height=580,
            column_config={
                "web_name": st.column_config.TextColumn("Player"),
                "team": st.column_config.TextColumn("Team"),
                "position": st.column_config.TextColumn("Pos", width="small"),
                "cost_m": st.column_config.NumberColumn("Cost", format="£%.1fm"),
                "total_points": st.column_config.NumberColumn("Pts"),
                "form": st.column_config.NumberColumn("Form", format="%.1f"),
                "ppg": st.column_config.NumberColumn("Pts/Game", format="%.1f"),
                "goals_scored": st.column_config.NumberColumn("Goals"),
                "assists": st.column_config.NumberColumn("Assists"),
                "clean_sheets": st.column_config.NumberColumn("CS"),
                "value": st.column_config.NumberColumn("Value", format="%.1f"),
                "selected_pct": st.column_config.NumberColumn("Sel%", format="%.1f%%"),
                "status": st.column_config.TextColumn("Status"),
            },
        )

    # ── Best Value ────────────────────────────────────────────────────────────
    elif league_page == "Best Value":
        st.title("Best value players")
        st.caption("Value = Total Points ÷ Cost (£m)")

        c1, c2 = st.columns(2)
        with c1:
            pos = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
        with c2:
            min_min = st.slider("Min. minutes played", 0, 3000, 450, 90)

        df = players_df[players_df["minutes"] >= min_min].copy()
        if pos != "All":
            df = df[df["position"] == pos]
        df = df.sort_values("value", ascending=False).head(20).reset_index(drop=True)
        df.index += 1

        col_l, col_r = st.columns([2, 1])
        with col_l:
            st.dataframe(
                df[["web_name", "team", "position", "cost_m", "total_points", "value", "form", "status"]],
                width="stretch",
                column_config={
                    "web_name": st.column_config.TextColumn("Player"),
                    "team": st.column_config.TextColumn("Team"),
                    "position": st.column_config.TextColumn("Pos", width="small"),
                    "cost_m": st.column_config.NumberColumn("Cost", format="£%.1fm"),
                    "total_points": st.column_config.NumberColumn("Pts"),
                    "value": st.column_config.NumberColumn("Value (pts/£m)", format="%.1f"),
                    "form": st.column_config.NumberColumn("Form", format="%.1f"),
                    "status": st.column_config.TextColumn("Status"),
                },
            )
        with col_r:
            st.subheader("Value vs Points")
            st.scatter_chart(df.set_index("web_name")[["value", "total_points"]], x="value", y="total_points")

    # ── Form Table ────────────────────────────────────────────────────────────
    elif league_page == "Form Table":
        st.title("In-form players")

        c1, c2 = st.columns(2)
        with c1:
            pos = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
        with c2:
            sort_by = st.selectbox(
                "Sort by", ["form", "ppg", "total_points"],
                format_func=lambda c: {"form": "Form", "ppg": "Pts/Game", "total_points": "Total Points"}[c],
            )

        df = players_df.copy()
        if pos != "All":
            df = df[df["position"] == pos]
        df = df.sort_values(sort_by, ascending=False).head(25).reset_index(drop=True)
        df.index += 1

        st.dataframe(
            df[["web_name", "team", "position", "cost_m", "form", "ppg", "total_points", "goals_scored", "assists", "status"]],
            width="stretch",
            column_config={
                "web_name": st.column_config.TextColumn("Player"),
                "team": st.column_config.TextColumn("Team"),
                "position": st.column_config.TextColumn("Pos", width="small"),
                "cost_m": st.column_config.NumberColumn("Cost", format="£%.1fm"),
                "form": st.column_config.NumberColumn("Form", format="%.1f"),
                "ppg": st.column_config.NumberColumn("Pts/Game", format="%.1f"),
                "total_points": st.column_config.NumberColumn("Total Pts"),
                "goals_scored": st.column_config.NumberColumn("Goals"),
                "assists": st.column_config.NumberColumn("Assists"),
                "status": st.column_config.TextColumn("Status"),
            },
        )

    # ── Fixture Difficulty ────────────────────────────────────────────────────
    elif league_page == "Fixture Difficulty":
        st.title("Fixture difficulty")
        st.caption("Difficulty rating 1 (easiest) → 5 (hardest), from each team's perspective.")

        next_n = st.slider("Gameweeks ahead", 3, 10, 6)
        heatmap = _build_heatmap(fixtures_df, current_gw, next_n)

        if heatmap.empty:
            st.warning("No upcoming fixture data available.")
        else:
            gw_cols = [c for c in heatmap.columns if c.startswith("GW")]

            def _diff_color(val: float) -> str:
                colors = {1: "#2f9e6f", 2: "#9bd3b7", 3: "#f2d675", 4: "#e69a55", 5: "#c94a57"}
                return "background-color: #f4f2f5; color: #777" if pd.isna(val) else f"background-color: {colors.get(int(val), '#fff')}; color: #111"

            st.dataframe(
                heatmap.style.map(_diff_color, subset=gw_cols),
                width="stretch",
                height=700,
            )
            st.caption("1 easy · 3 medium · 5 hard")


# ---------------------------------------------------------------------------
# ══ PERSONAL PAGES ══════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif active_section == "personal" and manager_profile and season:

    _manager_banner(manager_profile, manager_gameweek)

    # ── My Season ─────────────────────────────────────────────────────────────
    if personal_page == "My Season":
        st.header("Current team")
        st.caption(f"Your latest public selection from Gameweek {manager_gameweek}. Sale values include FPL's profit rule.")

        if squad_error:
            st.error("The current squad could not be loaded from FPL.", icon=":material/error:")
        elif manager_squad.empty:
            st.warning("No public picks are available for this manager yet.", icon=":material/warning:")
        else:
            squad_checks = validate_squad(manager_squad)
            if not all(squad_checks.values()):
                st.warning("FPL returned an incomplete or invalid 15-player squad.", icon=":material/warning:")
            st.html(render_pitch(manager_squad, manager_gameweek))

            st.subheader("Squad details")
            squad_details = manager_squad.copy()
            squad_details["player"] = squad_details.apply(
                lambda player: f"{player['web_name']} (C)" if player["is_captain"] else f"{player['web_name']} (V)" if player["is_vice_captain"] else player["web_name"],
                axis=1,
            )
            squad_details["role"] = squad_details["squad_pos"].map(lambda squad_position: "Starting XI" if squad_position <= 11 else f"Bench {squad_position - 11}")
            squad_details["current_price"] = squad_details["now_cost"] / 10
            squad_details["sale_price"] = squad_details["selling_price"] / 10
            squad_details["availability"] = squad_details["status"].map(_status_badge)
            st.dataframe(
                squad_details[["player", "team_short", "position", "role", "event_points", "current_price", "sale_price", "next_fixture", "availability"]],
                width="stretch",
                hide_index=True,
                column_config={
                    "player": st.column_config.TextColumn("Player", pinned=True),
                    "team_short": st.column_config.TextColumn("Club"),
                    "position": st.column_config.TextColumn("Pos."),
                    "role": st.column_config.TextColumn("Line-up"),
                    "event_points": st.column_config.NumberColumn(f"GW{manager_gameweek} pts"),
                    "current_price": st.column_config.NumberColumn("Market price", format="£%.1fm"),
                    "sale_price": st.column_config.NumberColumn("Your sale price", format="£%.1fm"),
                    "next_fixture": st.column_config.TextColumn(f"GW{next_gw}"),
                    "availability": st.column_config.TextColumn("Status"),
                },
            )

    # ── My Decisions ──────────────────────────────────────────────────────────
    elif personal_page == "My Decisions":
        st.header("Decision review")
        st.caption("Public gameweek history and completed transfers for this season.")

        current_history = pd.DataFrame(manager_history.get("current", []))
        if current_history.empty:
            st.info("No gameweek history is available yet.", icon=":material/info:")
        else:
            total_transfers = int(current_history["event_transfers"].sum())
            hit_points = int(current_history["event_transfers_cost"].sum())
            bench_points = int(current_history["points_on_bench"].sum())
            with st.container(horizontal=True):
                st.metric("Transfers", total_transfers, border=True)
                st.metric("Points spent", hit_points, border=True)
                st.metric("Points benched", bench_points, border=True)
            history_chart = current_history[["event", "points"]].rename(columns={"event": "Gameweek", "points": "Points"})
            st.line_chart(history_chart.set_index("Gameweek"))
            history_table = current_history[["event", "points", "total_points", "overall_rank", "bank", "value", "event_transfers", "event_transfers_cost", "points_on_bench"]].copy()
            history_table["bank"] = history_table["bank"] / 10
            history_table["value"] = history_table["value"] / 10
            st.dataframe(
                history_table,
                width="stretch",
                hide_index=True,
                column_config={
                    "event": st.column_config.NumberColumn("GW"),
                    "points": st.column_config.NumberColumn("Points"),
                    "total_points": st.column_config.NumberColumn("Total"),
                    "overall_rank": st.column_config.NumberColumn("Overall rank", format="localized"),
                    "bank": st.column_config.NumberColumn("Bank", format="£%.1fm"),
                    "value": st.column_config.NumberColumn("Team value", format="£%.1fm"),
                    "event_transfers": st.column_config.NumberColumn("Transfers"),
                    "event_transfers_cost": st.column_config.NumberColumn("Cost"),
                    "points_on_bench": st.column_config.NumberColumn("Bench pts"),
                },
            )

        st.subheader("Transfer history")
        transfer_history = pd.DataFrame(manager_transfers)
        if transfer_history.empty:
            st.caption("No completed transfers this season.")
        else:
            player_names = players_df.set_index("id")["web_name"].to_dict()
            transfer_history["sold"] = transfer_history["element_out"].map(player_names)
            transfer_history["bought"] = transfer_history["element_in"].map(player_names)
            transfer_history["sale_price"] = transfer_history["element_out_cost"] / 10
            transfer_history["buy_price"] = transfer_history["element_in_cost"] / 10
            st.dataframe(
                transfer_history[["event", "sold", "sale_price", "bought", "buy_price", "time"]],
                width="stretch",
                hide_index=True,
                column_config={
                    "event": st.column_config.NumberColumn("GW"),
                    "sold": st.column_config.TextColumn("Sold"),
                    "sale_price": st.column_config.NumberColumn("Sale", format="£%.1fm"),
                    "bought": st.column_config.TextColumn("Bought"),
                    "buy_price": st.column_config.NumberColumn("Cost", format="£%.1fm"),
                    "time": st.column_config.DatetimeColumn("Completed", format="D MMM, HH:mm"),
                },
            )

    # ── Recommendations ────────────────────────────────────────────────────────
    elif personal_page == "Recommendations":
        st.header("Transfer planner")
        st.caption("Affordable one-for-one moves from your current 15-player squad. Every result is checked against FPL squad rules.")

        if squad_error:
            st.error("The current squad could not be loaded from FPL.", icon=":material/error:")
        elif manager_squad.empty:
            st.warning("No public picks are available for this manager yet.", icon=":material/warning:")
        elif not all(validate_squad(manager_squad).values()):
            st.error("Recommendations are paused because FPL did not return a valid 15-player squad.", icon=":material/error:")
        else:
            control_one, control_two, control_three = st.columns(3)
            with control_one:
                horizon = st.segmented_control(
                    "Projection window",
                    [3, 5],
                    default=3,
                    required=True,
                    format_func=lambda gameweeks: f"{gameweeks} GWs",
                    key="projection_horizon",
                )
            with control_two:
                hit_cost = st.segmented_control(
                    "Transfer cost",
                    [0, 4],
                    default=0,
                    required=True,
                    format_func=lambda cost: "Free" if cost == 0 else "-4 points",
                    key="transfer_cost",
                )
            with control_three:
                selected_position = st.selectbox(
                    "Position",
                    ["All", "GKP", "DEF", "MID", "FWD"],
                    key="transfer_position",
                )
            include_doubtful = st.toggle("Include players with a 75% chance of playing", value=False, key="include_doubtful")

            outgoing_pool = manager_squad if selected_position == "All" else manager_squad[manager_squad["position"] == selected_position]
            outgoing_options = [0] + outgoing_pool["id"].astype(int).tolist()
            outgoing_names = outgoing_pool.set_index("id")["web_name"].to_dict()
            selected_outgoing = st.selectbox(
                "Player to replace",
                outgoing_options,
                format_func=lambda player_id: "Best move across the squad" if player_id == 0 else outgoing_names[player_id],
                key="outgoing_player",
            )

            recommendations = recommend_transfers(
                manager_squad,
                players_df,
                fixtures_df,
                bank=manager_profile["bank_units"],
                next_gameweek=next_gw,
                horizon=int(horizon),
                position=None if selected_position == "All" else selected_position,
                include_doubtful=include_doubtful,
            )
            recommendations["net_gain"] = recommendations["projected_gain"] - int(hit_cost)
            if selected_outgoing:
                recommendations = recommendations[recommendations["player_out_id"] == selected_outgoing]
            else:
                recommendations = recommendations.drop_duplicates("player_in_id")
            recommendations = recommendations.sort_values(["net_gain", "player_in_projection"], ascending=False)
            positive_moves = recommendations[recommendations["net_gain"] > 0].head(8).copy()

            if positive_moves.empty:
                with st.container(border=True):
                    st.badge("Best decision", icon=":material/pause_circle:", color="green")
                    st.subheader("Hold the transfer")
                    st.write(f"No legal move improves the best starting-XI projection over {int(horizon)} gameweeks after a {int(hit_cost)}-point transfer cost.")
            else:
                best_move = positive_moves.iloc[0]
                outgoing_player = players_df[players_df["id"] == best_move["player_out_id"]].iloc[0]
                incoming_player = players_df[players_df["id"] == best_move["player_in_id"]].iloc[0]
                outgoing_fixtures = _fixture_run(fixtures_df, int(outgoing_player["team_id"]), next_gw, int(horizon))
                incoming_fixtures = _fixture_run(fixtures_df, int(incoming_player["team_id"]), next_gw, int(horizon))

                with st.container(border=True, key="primary-recommendation"):
                    st.badge("Best available move", icon=":material/recommend:", color="green")
                    st.subheader(f"{best_move['player_out']} → {best_move['player_in']}")
                    st.caption(
                        f"Sell {best_move['team_out']} · {best_move['position']} for £{best_move['selling_price'] / 10:.1f}m  |  "
                        f"Buy {best_move['team_in']} · {best_move['position']} for £{best_move['incoming_cost'] / 10:.1f}m"
                    )
                    st.markdown(
                        f"**{int(horizon)}-GW starting-XI gain:** :green[**+{best_move['net_gain']:.1f} points**]  ·  "
                        f"**Bank after:** £{best_move['bank_after'] / 10:.1f}m"
                    )
                    st.markdown(f"**{best_move['player_out']} fixtures:** {outgoing_fixtures}  \n**{best_move['player_in']} fixtures:** {incoming_fixtures}")
                    st.markdown(":green-badge[Same position] :green-badge[Within budget] :green-badge[Max 3 per club] :green-badge[Valid squad shape]")
                    st.caption(
                        f"Budget check: £{best_move['selling_price'] / 10:.1f}m sale value + £{manager_profile['bank']:.1f}m bank "
                        f"= £{best_move['available_budget'] / 10:.1f}m available. {best_move['player_in']} costs £{best_move['incoming_cost'] / 10:.1f}m."
                    )

                if len(positive_moves) > 1:
                    st.subheader("Other legal moves")
                    alternatives = positive_moves.iloc[1:].copy()
                    alternatives["sale"] = alternatives["selling_price"] / 10
                    alternatives["cost"] = alternatives["incoming_cost"] / 10
                    alternatives["bank_left"] = alternatives["bank_after"] / 10
                    st.dataframe(
                        alternatives[["player_out", "team_out", "player_in", "team_in", "position", "sale", "cost", "net_gain", "bank_left"]],
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "player_out": st.column_config.TextColumn("Sell", pinned=True),
                            "team_out": st.column_config.TextColumn("From"),
                            "player_in": st.column_config.TextColumn("Buy"),
                            "team_in": st.column_config.TextColumn("Club"),
                            "position": st.column_config.TextColumn("Pos."),
                            "sale": st.column_config.NumberColumn("Sale", format="£%.1fm"),
                            "cost": st.column_config.NumberColumn("Cost", format="£%.1fm"),
                            "net_gain": st.column_config.NumberColumn("Starting-XI gain", format="%+.1f pts"),
                            "bank_left": st.column_config.NumberColumn("Bank after", format="£%.1fm"),
                        },
                    )

            with st.expander("How recommendations are ranked", icon=":material/calculate:"):
                st.write("Player projections combine current FPL form (55%), points per game (30%), and FPL's next-gameweek estimate (15%). Official fixture difficulty is applied across the selected window, later gameweeks are discounted by 15%, and season minutes reduce the score of rotation risks. Transfer gain compares the highest-scoring legal starting XI before and after the move.")
                st.write("Unavailable players are excluded. Doubtful players are excluded unless the 75% option is enabled. Prices are calculated in £0.1m units to avoid rounding errors.")
                st.write("For players who rose in price, sale value follows the FPL half-profit rule. Purchase prices are reconstructed from transfer history; unchanged original picks use their season-start price.")

            st.subheader(f"Current formation · {formation_label(manager_squad)}")
            st.html(render_pitch(manager_squad, manager_gameweek))
