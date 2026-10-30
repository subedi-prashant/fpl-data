"""Streamlit helpers shared by every dashboard page."""

from __future__ import annotations

import pandas as pd
import requests
import streamlit as st

from dashboard.data import Manager, load_manager
from fpl_data.projections import Projections

MANAGER_KEY = "manager"
HORIZON_OPTIONS = [1, 3, 5]
DEFAULT_HORIZON = 5


def manager_id() -> int:
    raw = str(st.session_state.get(MANAGER_KEY) or "").strip()
    return int(raw) if raw.isdigit() else 0


def current_manager() -> tuple[Manager | None, str]:
    """The loaded manager, or an error message to show next to the ID field."""
    identifier = manager_id()
    if not identifier:
        return None, ""
    try:
        return load_manager(identifier), ""
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            return None, f"No public FPL team has ID {identifier}. Check the number in your team's URL."
        return None, "FPL didn't respond. Try again in a minute or use Refresh data."
    except requests.RequestException:
        return None, "Couldn't reach the FPL servers. Check your connection and use Refresh data."


def require_manager() -> Manager:
    """Return the loaded manager or render the onboarding empty state and stop."""
    manager, error = current_manager()
    if manager is not None and not manager.squad.empty:
        return manager
    with st.container(border=True):
        st.subheader("Load your FPL team to start")
        if error:
            st.warning("That manager ID couldn't be loaded. See the message under the ID field in the sidebar.", icon=":material/error:")
        elif manager is not None:
            st.warning("This team has no public picks yet. Picks appear after the first deadline.", icon=":material/schedule:")
        st.markdown(
            "Enter your **manager ID** in the sidebar. It's the number after `/entry/` in your team's points page URL, "
            "for example `fantasy.premierleague.com/entry/1234567/event/9`."
        )
        st.caption("No login is needed. Only public team data is read, and nothing is stored.")
    st.stop()


def window(projections: Projections, horizon: int) -> list[int]:
    return projections.gameweeks[:horizon]


def with_window_xp(players: pd.DataFrame, gameweeks: list[int]) -> pd.DataFrame:
    players = players.copy()
    players["xp_window"] = players[[f"xp_gw{gameweek}" for gameweek in gameweeks]].sum(axis=1) if gameweeks else 0.0
    players["xp_window_list"] = [list(row) for row in players[[f"xp_gw{gameweek}" for gameweek in gameweeks]].round(2).to_numpy()] if gameweeks else [[] for _ in range(len(players))]
    return players


def team_runs(projections: Projections, gameweeks: list[int]) -> pd.DataFrame:
    return projections.team_fixtures[projections.team_fixtures["gw"].isin(gameweeks)]


def money(tenths: float) -> str:
    return f"£{tenths / 10:.1f}m"


def gameweek_span(gameweeks: list[int]) -> str:
    if not gameweeks:
        return "no upcoming gameweeks"
    return f"GW{gameweeks[0]}" if len(gameweeks) == 1 else f"GW{gameweeks[0]}–{gameweeks[-1]}"
