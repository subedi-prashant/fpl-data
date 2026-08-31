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

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fpl_data.analysis import (
    load_manager_history,
    load_manager_picks,
    load_manager_profile,
    transfer_quality_analysis,
    captaincy_analysis,
    bench_impact,
    vs_average_performance,
    optimal_team_suggestion,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="My FPL",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

_DB_PATH = _ROOT / "data" / "fpl.db"
_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_STATUS_LABEL = {"a": "✅ Available", "d": "🟡 Doubtful", "i": "🔴 Injured", "u": "⬛ Unavailable", "s": "🔵 Suspended"}

# ---------------------------------------------------------------------------
# Custom CSS — tighten spacing and style section headers
# ---------------------------------------------------------------------------

st.markdown("""
<style>
[data-testid="stSidebar"] .stMarkdown h3 { font-size: 0.78rem; text-transform: uppercase;
    letter-spacing: 0.08em; color: #888; margin: 1rem 0 0.3rem; }
[data-testid="stSidebar"] hr { margin: 0.4rem 0; border-color: #333; }
div[data-testid="metric-container"] { background: #1e1e2e; border-radius: 8px;
    padding: 0.8rem 1rem; border: 1px solid #2d2d3d; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Data helpers
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

@st.cache_data(ttl=6 * 3600)
def _get_manager_profile(mid: int) -> dict | None:
    return load_manager_profile(_DB_PATH, mid) if _USE_DB else None


@st.cache_data(ttl=6 * 3600)
def _get_manager_seasons(mid: int) -> list[int]:
    if not _USE_DB:
        return []
    hist = load_manager_history(_DB_PATH, mid)
    return sorted(hist["season"].unique().tolist(), reverse=True) if not hist.empty else []


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("⚽ My FPL")

# ── League Data ──────────────────────────────────────────────────────────────
st.sidebar.markdown("### 🌐 League Data")
league_page = st.sidebar.radio(
    "league_nav",
    ["Overview", "Player Explorer", "Best Value", "Form Table", "Fixture Difficulty"],
    label_visibility="collapsed",
)

# ── My FPL ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### 👤 My FPL")

raw_mid = st.sidebar.text_input(
    "Manager ID",
    placeholder="e.g. 7540623",
    help="Find your ID in your FPL profile URL: fantasy.premierleague.com/entry/**ID**/",
)
manager_id = int(raw_mid) if raw_mid.strip().isdigit() else 0
has_manager = manager_id > 0 and _USE_DB

manager_profile: dict | None = None
season: int | None = None

if has_manager:
    manager_profile = _get_manager_profile(manager_id)
    available_seasons = _get_manager_seasons(manager_id)

    if manager_profile and available_seasons:
        # Inline status chip
        rank_str = f"#{manager_profile['rank']:,}" if manager_profile["rank"] else "Unranked"
        st.sidebar.success(f"**{manager_profile['team_name']}** · {rank_str}")
        season = st.sidebar.selectbox("Season", available_seasons, index=0)
        personal_page = st.sidebar.radio(
            "my_fpl_nav",
            ["My Season", "My Decisions", "Recommendations"],
            label_visibility="collapsed",
        )
    else:
        st.sidebar.warning("No data found — run `fpl-data fetch-manager` first.")
        personal_page = None
elif manager_id > 0 and not _USE_DB:
    st.sidebar.info("Personal data requires a local DB. Run `fpl-data fetch-all` first.")
    personal_page = None
else:
    personal_page = None

# Determine active section: personal pages take over when selected
active_section = "personal" if (personal_page and manager_profile) else "league"

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption(f"Source: {'Local DB' if _USE_DB else 'Live API'}")

# ---------------------------------------------------------------------------
# Load public data
# ---------------------------------------------------------------------------

players_df = get_players_df()
fixtures_df = get_fixtures_df()
gameweeks_df = get_gameweeks_df()
current_gw = get_current_gw(gameweeks_df)


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------

def _manager_banner(profile: dict, gw: int) -> None:
    """Sticky profile strip shown at the top of every personal page."""
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(f"**{profile['team_name']}**  \n*{profile['name']}*")
    c2.metric("GW", gw)
    c3.metric("Season Pts", profile["total_points"])
    rank_disp = f"{profile['rank']:,}" if profile["rank"] else "—"
    c4.metric("Overall Rank", rank_disp)
    c5.metric("Team Value", f"£{profile['team_value']:.1f}m")
    st.markdown("---")


def _status_badge(s: str) -> str:
    return _STATUS_LABEL.get(s, s)


# ---------------------------------------------------------------------------
# ══ LEAGUE PAGES ════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

if active_section == "league":

    # ── Overview ─────────────────────────────────────────────────────────────
    if league_page == "Overview":
        st.title("⚽ FPL Dashboard")
        st.caption(f"2025-26 Premier League season · Gameweek {current_gw}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Players", f"{len(players_df):,}")
        c2.metric("Teams", players_df["team"].nunique())
        c3.metric("Fixtures", f"{len(fixtures_df):,}")
        c4.metric("Current GW", current_gw)

        st.markdown("---")

        col_l, col_r = st.columns([3, 2])
        with col_l:
            st.subheader("🏆 Top 10 by Total Points")
            top10 = (
                players_df.sort_values("total_points", ascending=False)
                .head(10)[["web_name", "team", "position", "cost_m", "total_points", "form", "value"]]
                .reset_index(drop=True)
            )
            top10.index += 1
            st.dataframe(
                top10,
                use_container_width=True,
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
            st.subheader("📊 Avg Points by Position")
            pos_stats = (
                players_df.groupby("position")["total_points"].mean().round(1).reset_index()
            )
            pos_stats.columns = ["Position", "Avg Points"]
            st.bar_chart(pos_stats.set_index("Position"))

    # ── Player Explorer ───────────────────────────────────────────────────────
    elif league_page == "Player Explorer":
        st.title("📊 Player Explorer")

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
            use_container_width=True,
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
        st.title("💎 Best Value Players")
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
                use_container_width=True,
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
        st.title("🔥 In-Form Players")

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
            use_container_width=True,
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
        st.title("📅 Fixture Difficulty")
        st.caption("Difficulty rating 1 (easiest) → 5 (hardest), from each team's perspective.")

        next_n = st.slider("Gameweeks ahead", 3, 10, 6)
        heatmap = _build_heatmap(fixtures_df, current_gw, next_n)

        if heatmap.empty:
            st.warning("No upcoming fixture data available.")
        else:
            gw_cols = [c for c in heatmap.columns if c.startswith("GW")]

            def _diff_color(val: float) -> str:
                colors = {1: "#2ecc71", 2: "#a8d8a8", 3: "#f0e68c", 4: "#f39c12", 5: "#e74c3c"}
                return f"background-color: {colors.get(int(val), '#fff')}; color: #111"

            st.dataframe(
                heatmap.style.applymap(_diff_color, subset=gw_cols),
                use_container_width=True,
                height=700,
            )
            st.caption("🟢 1 Easy   🟡 3 Medium   🔴 5 Hard")


# ---------------------------------------------------------------------------
# ══ PERSONAL PAGES ══════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif active_section == "personal" and manager_profile and season:

    _manager_banner(manager_profile, current_gw)

    # ── My Season ─────────────────────────────────────────────────────────────
    if personal_page == "My Season":
        st.header("📋 My Season")

        tab_profile, tab_history, tab_bench_mark = st.tabs(["Profile", "Season History", "Benchmarking"])

        with tab_profile:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Points", manager_profile["total_points"])
            rank_disp = f"{manager_profile['rank']:,}" if manager_profile["rank"] else "—"
            c2.metric("Overall Rank", rank_disp)
            c3.metric("Team Value", f"£{manager_profile['team_value']:.1f}m")
            c4.metric("Bank", f"£{manager_profile['bank']:.1f}m")

        with tab_history:
            hist = load_manager_history(_DB_PATH, manager_id)
            if hist.empty:
                st.info("No season history found.")
            else:
                st.dataframe(
                    hist[["season", "total_points", "rank", "transfers_used", "finished"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "season": st.column_config.NumberColumn("Season", format="%d"),
                        "total_points": st.column_config.NumberColumn("Points"),
                        "rank": st.column_config.NumberColumn("Final Rank"),
                        "transfers_used": st.column_config.NumberColumn("Transfers"),
                        "finished": st.column_config.CheckboxColumn("Completed"),
                    },
                )
                st.line_chart(hist.set_index("season")["total_points"])

        with tab_bench_mark:
            perf = vs_average_performance(_DB_PATH, manager_id, season)
            if not perf:
                st.info("Not enough data for benchmarking yet.")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Your Points", perf["manager_points"])
                c2.metric("League Average", f"{perf['league_avg_points']:.0f}")
                delta = perf["points_above_average"]
                c3.metric("vs Average", f"{delta:+.0f} pts", delta_color="normal")
                if perf.get("estimated_rank_percentile"):
                    st.info(f"📍 You're in the **top {perf['estimated_rank_percentile']:.1f}%** of all managers (est.)")
                comp = pd.DataFrame({
                    "Category": ["Your Points", "League Avg"],
                    "Points": [perf["manager_points"], perf["league_avg_points"]],
                })
                st.bar_chart(comp.set_index("Category"))

    # ── My Decisions ──────────────────────────────────────────────────────────
    elif personal_page == "My Decisions":
        st.header("⚡ My Decisions")

        tab_picks, tab_transfers, tab_capt, tab_bench = st.tabs(
            ["My Picks", "Transfers", "Captaincy", "Bench"]
        )

        with tab_picks:
            picks = load_manager_picks(_DB_PATH, manager_id, season)
            if picks.empty:
                st.info("No picks found. Run `fpl-data fetch-manager` to load your team selections.")
            else:
                c1, c2 = st.columns([2, 3])
                with c1:
                    selected_gw = st.selectbox("Gameweek", sorted(picks["gameweek"].unique()))
                gw_picks = picks[picks["gameweek"] == selected_gw].sort_values("position")
                starters = gw_picks[gw_picks["squad_pos"] < 12]
                bench_p = gw_picks[gw_picks["squad_pos"] >= 12]

                st.markdown(f"**GW{selected_gw} · {len(gw_picks)} players · {int(gw_picks['points'].sum())} pts**")
                col_xi, col_bench = st.columns(2)

                with col_xi:
                    st.caption(f"Starting XI ({len(starters)})")
                    st.dataframe(
                        starters[["web_name", "team", "is_captain", "is_vice_captain", "points"]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "web_name": st.column_config.TextColumn("Player"),
                            "team": st.column_config.TextColumn("Team"),
                            "is_captain": st.column_config.CheckboxColumn("©"),
                            "is_vice_captain": st.column_config.CheckboxColumn("vc"),
                            "points": st.column_config.NumberColumn("Pts"),
                        },
                    )
                with col_bench:
                    st.caption(f"Bench ({len(bench_p)})")
                    if not bench_p.empty:
                        st.dataframe(
                            bench_p[["web_name", "team", "points"]],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "web_name": st.column_config.TextColumn("Player"),
                                "team": st.column_config.TextColumn("Team"),
                                "points": st.column_config.NumberColumn("Pts"),
                            },
                        )

        with tab_transfers:
            transfers_df = transfer_quality_analysis(_DB_PATH, manager_id, season)
            if transfers_df.empty:
                st.info("No transfers found for this season.")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Transfers Made", len(transfers_df))
                c2.metric("Avg Net Gain", f"{transfers_df['net_gain'].mean():+.1f} pts")
                good = len(transfers_df[transfers_df["quality"] == "Good"])
                c3.metric("Good Transfers", f"{good}/{len(transfers_df)}")
                st.markdown("---")

                def _tcolor(val: str) -> str:
                    return {"Good": "background-color:#1a5c3a;color:#fff",
                            "Okay": "background-color:#5c4a00;color:#fff",
                            "Poor": "background-color:#5c1a1a;color:#fff"}.get(val, "")

                disp = transfers_df.copy()
                disp.columns = ["GW", "Sold", "Bought", "Cost (£)", "Sold 3GW", "Bought 3GW", "Net Pts", "Quality"]
                st.dataframe(
                    disp.style.map(_tcolor, subset=["Quality"]),
                    use_container_width=True,
                    hide_index=True,
                )

        with tab_capt:
            capt_df = captaincy_analysis(_DB_PATH, manager_id, season)
            if capt_df.empty:
                st.info("No captaincy data found.")
            else:
                optimal = len(capt_df[capt_df["decision_quality"] == "Optimal"])
                missed_total = int(capt_df["opportunity_cost"].sum())
                c1, c2, c3 = st.columns(3)
                c1.metric("Optimal Captains", f"{optimal}/{len(capt_df)}")
                c2.metric("Points Missed", missed_total)
                c3.metric("Avg Opp. Cost", f"{capt_df['opportunity_cost'].mean():.1f} pts")
                st.markdown("---")

                def _ccolor(val: str) -> str:
                    return "background-color:#1a5c3a;color:#fff" if val == "Optimal" else "background-color:#5c3a00;color:#fff"

                disp = capt_df.copy()
                disp.columns = ["GW", "Chosen", "Chosen Pts", "Best Option", "Best Pts", "Pts Missed", "Decision"]
                disp["Pts Missed"] = disp["Pts Missed"].astype(int)
                st.dataframe(
                    disp.style.map(_ccolor, subset=["Decision"]),
                    use_container_width=True,
                    hide_index=True,
                )

        with tab_bench:
            bench_df = bench_impact(_DB_PATH, manager_id, season)
            if bench_df.empty:
                st.info("No bench data found.")
            else:
                missed_opps = len(bench_df[bench_df["missed_opportunity"] == "Yes"])
                c1, c2, c3 = st.columns(3)
                c1.metric("High-scoring bench GWs", missed_opps)
                c2.metric("Total bench points", int(bench_df["bench_points"].sum()))
                c3.metric("Avg best bench score", f"{bench_df['bench_points'].mean():.1f}")
                st.markdown("---")

                def _bcolor(val: str) -> str:
                    return "background-color:#5c1a1a;color:#fff" if val == "Yes" else ""

                disp = bench_df.copy()
                disp.columns = ["GW", "Top Benched", "Pts", "Position", "High Scorer?"]
                st.dataframe(
                    disp.style.map(_bcolor, subset=["High Scorer?"]),
                    use_container_width=True,
                    hide_index=True,
                )

    # ── Recommendations ────────────────────────────────────────────────────────
    elif personal_page == "Recommendations":
        st.header("🤖 Team Recommendations")
        st.caption("Suggested picks based on form, fixture difficulty and recent points.")

        c1, c2 = st.columns(2)
        with c1:
            gw_rec = st.slider("Gameweek", 1, 38, current_gw)
        with c2:
            budget_rec = st.slider("Budget (£m)", 80.0, 110.0, 100.0, 0.5)

        rec_team = optimal_team_suggestion(_DB_PATH, manager_id, gw_rec, budget_rec)
        if rec_team.empty:
            st.warning("Not enough data to generate recommendations yet.")
        else:
            total_cost = rec_team["cost_m"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Players", len(rec_team))
            c2.metric("Total Cost", f"£{total_cost:.1f}m")
            c3.metric("Budget Left", f"£{budget_rec - total_cost:.1f}m")
            st.markdown("---")
            st.dataframe(
                rec_team,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "web_name": st.column_config.TextColumn("Player"),
                    "team_short": st.column_config.TextColumn("Team"),
                    "position": st.column_config.TextColumn("Pos", width="small"),
                    "cost_m": st.column_config.NumberColumn("Cost", format="£%.1fm"),
                    "form": st.column_config.NumberColumn("Form", format="%.1f"),
                    "avg_recent_points": st.column_config.NumberColumn("Recent Avg", format="%.1f"),
                    "pick_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=20),
                },
            )
