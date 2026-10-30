from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import ui
from dashboard.data import load_league, load_projections
from fpl_data.frames import STATUS_LABELS

league = load_league()
projections = load_projections()
manager, _ = ui.current_manager()

st.title("Injuries & news")
st.caption("Every player FPL has flagged, with the expected return date from the official news and the projected points impact.")

flagged = projections.players[projections.players["status"] != "a"].copy()
with st.container(horizontal=True):
    for status in ["d", "i", "s"]:
        st.metric(STATUS_LABELS[status], int((flagged["status"] == status).sum()), border=True)

statuses = {"d": "Doubtful", "i": "Injured", "s": "Suspended", "u": "Left club or unavailable"}
with st.container(horizontal=True, gap="large"):
    chosen = st.pills("Status", list(statuses), selection_mode="multi", default=["d", "i", "s"], format_func=statuses.get, key="injuries_status")
    positions = st.pills("Position", ["GKP", "DEF", "MID", "FWD"], selection_mode="multi", default=["GKP", "DEF", "MID", "FWD"], key="injuries_positions")
    only_mine = st.toggle("Only my squad", value=False, key="injuries_mine", disabled=manager is None, help=None if manager else "Load your team in the sidebar to use this filter.")

squad_ids = set(manager.squad["id"]) if manager is not None and not manager.squad.empty else set()
first_fixture = league.fixtures.dropna(subset=["gw", "kickoff_time"]).sort_values("kickoff_time")


def expected_back(team_id: int, return_date: object, news: str) -> str:
    """'21 Nov (GW11)' when FPL gives a date, otherwise 'Unknown' or a dash."""
    if return_date is None or pd.isna(return_date):
        return "Unknown" if "unknown" in str(news).lower() else "—"
    upcoming = first_fixture[((first_fixture["team_h_id"] == team_id) | (first_fixture["team_a_id"] == team_id)) & (first_fixture["kickoff_time"].dt.normalize() >= return_date)]
    gameweek = f" (GW{int(upcoming.iloc[0]['gw'])})" if not upcoming.empty else ""
    return f"{return_date.day} {return_date.strftime('%b')}{gameweek}"


gameweeks = ui.window(projections, ui.DEFAULT_HORIZON)
flagged = ui.with_window_xp(flagged, gameweeks)
flagged["back"] = [expected_back(team_id, return_date, news) for team_id, return_date, news in zip(flagged["team_id"], flagged["return_date"], flagged["news"])]
flagged["mine"] = flagged["id"].isin(squad_ids)
flagged["chance_of_playing"] = pd.to_numeric(flagged["chance_of_playing"], errors="coerce")
mask = flagged["status"].isin(chosen or list(statuses)) & flagged["position"].isin(positions or ["GKP", "DEF", "MID", "FWD"])
if only_mine:
    mask &= flagged["mine"]
table = flagged[mask].sort_values(["mine", "selected_pct"], ascending=False)

if table.empty:
    st.success("No flagged players match these filters.", icon=":material/check_circle:")
else:
    st.dataframe(
        table[["web_name", "team_short", "position", "status_label", "chance_of_playing", "back", "news", "xp_window", "selected_pct", "mine", "news_added"]],
        hide_index=True,
        height="content" if len(table) <= 18 else 640,
        column_config={
            "web_name": st.column_config.TextColumn("Player", pinned=True),
            "team_short": st.column_config.TextColumn("Club"),
            "position": st.column_config.TextColumn("Pos."),
            "status_label": st.column_config.TextColumn("Status"),
            "chance_of_playing": st.column_config.NumberColumn("Chance", format="%d%%", help="FPL's chance of playing next round."),
            "back": st.column_config.TextColumn("Expected back", help="Parsed from the FPL news, with the first gameweek that has a fixture on or after that date."),
            "news": st.column_config.TextColumn("News", width="large"),
            "xp_window": st.column_config.NumberColumn("xP", format="%.1f", help=f"Projected points over {ui.gameweek_span(gameweeks)}, already discounted for the injury."),
            "selected_pct": st.column_config.NumberColumn("Owned", format="%.1f%%"),
            "mine": st.column_config.CheckboxColumn("In my squad"),
            "news_added": st.column_config.DatetimeColumn("Updated", format="D MMM, HH:mm"),
        },
    )
st.caption("Return dates are parsed from FPL's news text. Doubtful players are projected with their chance of playing, recovering over the following weeks.")
