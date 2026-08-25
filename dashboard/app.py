"""
FPL Dashboard — Streamlit app.

Works in two modes:
  • Local: reads from data/fpl.db (run `fpl-data fetch-all` first)
  • Cloud: fetches directly from the public FPL API (no DB needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# Allow importing fpl_data when running as `streamlit run dashboard/app.py`
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fpl_data.analysis import (
    best_value_players,
    fixture_difficulty_heatmap,
    player_form_last_n,
    top_performers,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FPL Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

_DB_PATH = _ROOT / "data" / "fpl.db"
_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# ---------------------------------------------------------------------------
# Data loading — cached so the app doesn't hammer the API on every interaction
# ---------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner="Fetching FPL data…")
def _fetch_bootstrap() -> dict:
    r = requests.get(
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=6 * 3600, show_spinner="Fetching fixtures…")
def _fetch_fixtures() -> list[dict]:
    r = requests.get(
        "https://fantasy.premierleague.com/api/fixtures/",
        headers={"User-Agent": "fpl-data-dashboard/0.1"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _build_players_df(bootstrap: dict) -> pd.DataFrame:
    teams = {t["id"]: t for t in bootstrap["teams"]}
    rows = []
    for p in bootstrap["elements"]:
        t = teams.get(p["team"], {})
        rows.append({
            "id": p["id"],
            "web_name": p["web_name"],
            "full_name": f"{p['first_name']} {p['second_name']}",
            "team": t.get("name", ""),
            "team_short": t.get("short_name", ""),
            "position": _POSITION_MAP.get(p["element_type"], "?"),
            "cost_m": p["now_cost"] / 10.0,
            "total_points": p["total_points"],
            "minutes": p.get("minutes", 0),
            "goals_scored": p.get("goals_scored", 0),
            "assists": p.get("assists", 0),
            "clean_sheets": p.get("clean_sheets", 0),
            "selected_pct": float(p.get("selected_by_percent", 0)),
            "form": float(p.get("form", 0)),
            "ppg": float(p.get("points_per_game", 0)),
            "status": p.get("status", "a"),
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
            "id": f["id"],
            "gw": f.get("event"),
            "team_h": th.get("name", ""),
            "team_h_short": th.get("short_name", ""),
            "team_a": ta.get("name", ""),
            "team_a_short": ta.get("short_name", ""),
            "team_h_difficulty": f.get("team_h_difficulty", 0),
            "team_a_difficulty": f.get("team_a_difficulty", 0),
            "team_h_score": f.get("team_h_score"),
            "team_a_score": f.get("team_a_score"),
            "finished": bool(f.get("finished", False)),
            "kickoff_time": f.get("kickoff_time"),
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
# Load data (API or local DB)
# ---------------------------------------------------------------------------

_USE_DB = _DB_PATH.exists()

if _USE_DB:
    @st.cache_data(ttl=6 * 3600)
    def get_players_df() -> pd.DataFrame:
        from fpl_data.analysis import load_players
        return load_players(_DB_PATH)

    @st.cache_data(ttl=6 * 3600)
    def get_fixtures_df() -> pd.DataFrame:
        from fpl_data.analysis import load_fixtures, load_gameweeks
        return load_fixtures(_DB_PATH)

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
        b = _fetch_bootstrap()
        return pd.DataFrame(b["events"])

    def get_current_gw(gws_df: pd.DataFrame) -> int:
        cur = gws_df[gws_df["is_current"] == True]["id"]
        return int(cur.iloc[0]) if not cur.empty else 1


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("⚽ FPL Dashboard")
st.sidebar.caption("Fantasy Premier League · Public data")

page = st.sidebar.radio(
    "Navigate",
    ["🏠 Overview", "📊 Player Explorer", "💎 Best Value", "🔥 Form Table", "📅 Fixture Difficulty"],
)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

data_source = "Local DB" if _USE_DB else "Live API"
st.sidebar.caption(f"Data source: {data_source}")

# Load data
players_df = get_players_df()
fixtures_df = get_fixtures_df()
gameweeks_df = get_gameweeks_df()
current_gw = get_current_gw(gameweeks_df)

# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

if page == "🏠 Overview":
    st.title("⚽ FPL Dashboard")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Players", len(players_df))
    c2.metric("Teams", players_df["team"].nunique())
    c3.metric("Fixtures", len(fixtures_df))
    c4.metric("Current GW", current_gw)

    st.markdown("---")
    st.subheader("🏆 Top 10 by Total Points")
    top10 = (
        players_df.sort_values("total_points", ascending=False)
        .head(10)[["web_name", "team", "position", "cost_m", "total_points", "form", "value"]]
        .reset_index(drop=True)
    )
    top10.index += 1
    st.dataframe(
        top10.rename(columns={"web_name": "Player", "cost_m": "Cost (£m)", "total_points": "Pts", "value": "Value"}),
        use_container_width=True,
    )

    st.subheader("📈 Points Distribution by Position")
    pos_stats = (
        players_df.groupby("position")
        .agg(avg_pts=("total_points", "mean"), count=("id", "count"))
        .round(1)
        .reset_index()
    )
    st.bar_chart(pos_stats.set_index("position")["avg_pts"])


elif page == "📊 Player Explorer":
    st.title("📊 Player Explorer")

    col1, col2, col3 = st.columns(3)
    with col1:
        pos_filter = st.multiselect("Position", ["GKP", "DEF", "MID", "FWD"], default=["GKP", "DEF", "MID", "FWD"])
    with col2:
        price_range = st.slider("Max price (£m)", 4.0, 15.0, 15.0, 0.5)
    with col3:
        status_filter = st.multiselect("Status", ["a", "d", "i", "u"], default=["a"], help="a=available d=doubtful i=injured u=unavailable")

    sort_col = st.selectbox("Sort by", ["total_points", "form", "ppg", "value", "cost_m", "goals_scored", "assists"], index=0)

    filtered = players_df[
        players_df["position"].isin(pos_filter)
        & (players_df["cost_m"] <= price_range)
        & players_df["status"].isin(status_filter)
    ].sort_values(sort_col, ascending=False)

    st.caption(f"Showing {len(filtered)} players")
    st.dataframe(
        filtered[["web_name", "team", "position", "cost_m", "total_points", "form", "ppg", "goals_scored", "assists", "clean_sheets", "value", "selected_pct", "status"]]
        .rename(columns={
            "web_name": "Player", "cost_m": "Cost (£m)", "total_points": "Pts",
            "ppg": "Pts/Game", "value": "Value", "selected_pct": "Sel%",
        })
        .reset_index(drop=True),
        use_container_width=True,
        height=600,
    )


elif page == "💎 Best Value":
    st.title("💎 Best Value Players")
    st.caption("Value = Total Points ÷ Cost (£m). Higher = better bang for your buck.")

    col1, col2 = st.columns(2)
    with col1:
        pos = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    with col2:
        min_min = st.slider("Min. minutes played", 0, 3000, 450, 90)

    df = players_df[players_df["minutes"] >= min_min].copy()
    if pos != "All":
        df = df[df["position"] == pos]
    df = df.sort_values("value", ascending=False).head(20).reset_index(drop=True)
    df.index += 1

    st.dataframe(
        df[["web_name", "team", "position", "cost_m", "total_points", "value", "form", "status"]]
        .rename(columns={"web_name": "Player", "cost_m": "Cost (£m)", "total_points": "Pts", "value": "Value (pts/£m)"}),
        use_container_width=True,
    )

    st.markdown("---")
    st.subheader("Value vs Points scatter")
    chart_data = df.set_index("web_name")[["value", "total_points"]]
    st.scatter_chart(chart_data, x="value", y="total_points")


elif page == "🔥 Form Table":
    st.title("🔥 In-Form Players")

    col1, col2 = st.columns(2)
    with col1:
        pos = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    with col2:
        sort_by = st.selectbox("Sort by", ["form", "ppg", "total_points"])

    df = players_df.copy()
    if pos != "All":
        df = df[df["position"] == pos]
    df = df.sort_values(sort_by, ascending=False).head(25).reset_index(drop=True)
    df.index += 1

    st.dataframe(
        df[["web_name", "team", "position", "cost_m", "form", "ppg", "total_points", "goals_scored", "assists"]]
        .rename(columns={
            "web_name": "Player", "cost_m": "Cost (£m)",
            "ppg": "Pts/Game", "total_points": "Total Pts",
        }),
        use_container_width=True,
    )


elif page == "📅 Fixture Difficulty":
    st.title("📅 Fixture Difficulty")
    st.caption("Difficulty rating: 1 (easiest) → 5 (hardest), from each team's perspective.")

    next_n = st.slider("Gameweeks ahead", 3, 10, 6)

    heatmap = _build_heatmap(fixtures_df, current_gw, next_n)

    if heatmap.empty:
        st.warning("No upcoming fixture data available.")
    else:
        gw_cols = [c for c in heatmap.columns if c.startswith("GW")]

        def _color(val: float) -> str:
            colors = {1: "#2ecc71", 2: "#a8d8a8", 3: "#f0e68c", 4: "#f39c12", 5: "#e74c3c"}
            return f"background-color: {colors.get(int(val), '#ffffff')}; color: #111"

        styled = heatmap.style.applymap(_color, subset=gw_cols)
        st.dataframe(styled, use_container_width=True, height=700)

        st.markdown(
            "🟢 1 = Easy &nbsp;&nbsp; 🟡 3 = Medium &nbsp;&nbsp; 🔴 5 = Hard",
            unsafe_allow_html=True,
        )
