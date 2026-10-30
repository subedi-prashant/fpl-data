"""
My FPL dashboard entrypoint: page config, sidebar and navigation.

Every page reads live data from the public FPL API (cached for 15 minutes) and
the expected-points model in `fpl_data.projections`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# A stale pip-installed fpl-data can linger in hosted environments; make sure the
# repo package is the one that gets imported.
for _mod in [name for name in sys.modules if name == "fpl_data" or name.startswith("fpl_data.")]:
    del sys.modules[_mod]
import fpl_data  # noqa: F401

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from dashboard import data, ui

st.set_page_config(
    page_title="My FPL",
    page_icon=":material/sports_soccer:",
    layout="wide",
    initial_sidebar_state="auto",
)
_ASSETS = Path(__file__).parent / "assets"
st.logo(str(_ASSETS / "logo.svg"), size="large", icon_image=str(_ASSETS / "icon.svg"))

st.html("""
<style>
.st-key-hero-move { border-left: 4px solid #008a55; }
.st-key-hold-move { border-left: 4px solid #667085; }
</style>
""")

pages = {
    "Your team": [
        st.Page("app_pages/planner.py", title="Transfer planner", icon=":material/swap_horiz:", default=True),
        st.Page("app_pages/team.py", title="My team", icon=":material/groups:"),
        st.Page("app_pages/review.py", title="Decision review", icon=":material/query_stats:"),
    ],
    "League": [
        st.Page("app_pages/players.py", title="Players", icon=":material/person_search:"),
        st.Page("app_pages/fixtures.py", title="Fixtures", icon=":material/calendar_month:"),
        st.Page("app_pages/injuries.py", title="Injuries & news", icon=":material/medical_services:"),
    ],
}
page = st.navigation(pages, position="sidebar")
st.set_page_config(page_title=f"{page.title} · My FPL")

with st.sidebar:
    with st.form("manager_form", border=False):
        st.text_input(
            "Manager ID",
            value=os.getenv("FPL_MANAGER_ID", "").strip(),
            key=ui.MANAGER_KEY,
            placeholder="e.g. 1234567",
            help="The number in your team's points page URL: fantasy.premierleague.com/entry/1234567/event/9",
            bind="query-params",
            validate=(r"^\d{1,10}$", "Use the digits from your team URL, e.g. 1234567."),
        )
        st.form_submit_button("Load team", icon=":material/download:", type="primary", width="stretch")
    manager, manager_error = ui.current_manager()
    if manager is not None:
        rank = f"#{manager.rank:,}" if manager.rank else "Unranked"
        with st.container(border=True):
            st.markdown(f"**{manager.team_name}**")
            st.caption(f"{manager.name} · {rank} · {manager.total_points:,} pts")
    elif manager_error:
        st.error(manager_error, icon=":material/error:")
    if st.button("Refresh data", icon=":material/refresh:", width="stretch"):
        data.refresh()
        st.rerun()
    st.caption("Live public FPL data, refreshed every 15 minutes. No login needed.")

page.run()
