from __future__ import annotations

import streamlit as st

from dashboard import ui
from dashboard.components import fixture_run_text
from dashboard.data import load_projections

projections = load_projections()

st.title("Players")
st.caption("Every player ranked by projected points, with upcoming fixtures, recent form and availability.")

if not projections.gameweeks:
    st.info("There are no upcoming gameweeks to project.", icon=":material/event_busy:")
    st.stop()

sort_options = {
    "xp_window": "Projected points",
    "value_window": "Projected points per £m",
    "xgi90_recent": "Recent xGI per 90",
    "form": "FPL form",
    "total_points": "Season points",
    "selected_pct": "Ownership",
}
with st.container(border=True):
    with st.container(horizontal=True, gap="large"):
        search = st.text_input("Search", placeholder="Player or club", key="players_search", width=260)
        positions = st.pills("Position", ["GKP", "DEF", "MID", "FWD"], selection_mode="multi", default=["GKP", "DEF", "MID", "FWD"], key="players_positions")
        horizon = st.segmented_control(
            "Projection window",
            ui.HORIZON_OPTIONS,
            default=ui.DEFAULT_HORIZON,
            required=True,
            format_func=lambda gameweeks: f"{gameweeks} GW" if gameweeks == 1 else f"{gameweeks} GWs",
            key="players_horizon",
        )
    with st.container(horizontal=True, gap="large"):
        max_price = st.slider("Max price", 3.5, 16.0, 16.0, 0.5, format="£%.1fm", key="players_max_price", width=320)
        sort_by = st.selectbox("Sort by", list(sort_options), format_func=sort_options.get, key="players_sort", width=260)
        hide_flagged = st.toggle("Hide injured and unavailable", value=True, key="players_hide_flagged")

gameweeks = ui.window(projections, int(horizon))
team_fixtures = ui.team_runs(projections, gameweeks)
players = ui.with_window_xp(projections.players, gameweeks)
players["value_window"] = players["xp_window"] / players["cost_m"]
players["fixtures"] = players["team_id"].map({team_id: fixture_run_text(team_fixtures[team_fixtures["team_id"] == team_id], gameweeks[:3]) for team_id in players["team_id"].unique()})
mask = players["position"].isin(positions or ["GKP", "DEF", "MID", "FWD"]) & (players["cost_m"] <= max_price)
if hide_flagged:
    mask &= players["status"].isin(["a", "d"])
if search:
    needle = search.strip().lower()
    mask &= players["web_name"].str.lower().str.contains(needle, regex=False) | players["full_name"].str.lower().str.contains(needle, regex=False) | players["team"].str.lower().str.contains(needle, regex=False)
filtered = players[mask].sort_values(sort_by, ascending=False).reset_index(drop=True)

st.caption(f"{len(filtered)} players · projections for {ui.gameweek_span(gameweeks)}")
st.dataframe(
    filtered[["web_name", "team_short", "position", "cost_m", "xp_window", "value_window", "fixtures", "recent_points", "xgi90_recent", "xmins_next", "form", "total_points", "selected_pct", "status_label"]],
    hide_index=True,
    height=620,
    column_config={
        "web_name": st.column_config.TextColumn("Player", pinned=True),
        "team_short": st.column_config.TextColumn("Club"),
        "position": st.column_config.TextColumn("Pos."),
        "cost_m": st.column_config.NumberColumn("Price", format="£%.1fm"),
        "xp_window": st.column_config.NumberColumn("xP", format="%.1f", help=f"Projected points over {ui.gameweek_span(gameweeks)}."),
        "value_window": st.column_config.NumberColumn("xP per £m", format="%.2f"),
        "fixtures": st.column_config.TextColumn("Next 3 fixtures"),
        "recent_points": st.column_config.BarChartColumn("Last 5 GWs", y_min=0, y_max=15),
        "xgi90_recent": st.column_config.NumberColumn("xGI/90", format="%.2f", help="Expected goal involvements per 90 minutes over the last 4 gameweeks."),
        "xmins_next": st.column_config.NumberColumn("xMins", format="%.0f", help="Expected minutes next gameweek."),
        "form": st.column_config.NumberColumn("FPL form", format="%.1f", help="FPL's average points over the last 30 days."),
        "total_points": st.column_config.NumberColumn("Season pts"),
        "selected_pct": st.column_config.NumberColumn("Owned", format="%.1f%%"),
        "status_label": st.column_config.TextColumn("Status"),
    },
)
