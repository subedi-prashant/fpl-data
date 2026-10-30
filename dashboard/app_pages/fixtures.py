from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import ui
from dashboard.components import DIFFICULTY_BADGE_COLORS, difficulty_style
from dashboard.data import load_league, load_projections
from fpl_data.projections import DIFFICULTY_LABELS

league = load_league()
projections = load_projections()

st.title("Fixtures")
st.caption("Difficulty comes from our team model's expected goals for and against each match, not FPL's static 1–5 ratings.")

if projections.team_fixtures.empty:
    st.info("No upcoming fixtures are scheduled.", icon=":material/event_busy:")
    st.stop()

views = {
    "difficulty": "Overall difficulty",
    "attack": "Attack: expected goals",
    "defence": "Defence: clean-sheet chance",
}
with st.container(horizontal=True, gap="large"):
    view = st.segmented_control("Show", list(views), default="difficulty", required=True, format_func=views.get, key="fixtures_view")
    count = st.slider("Gameweeks", 1, len(projections.gameweeks), len(projections.gameweeks), key="fixtures_count", width=320)

gameweeks = projections.gameweeks[:count]
fixtures = projections.team_fixtures[projections.team_fixtures["gw"].isin(gameweeks)].copy()
if view == "attack":
    fixtures["cell"] = fixtures["label"] + " " + fixtures["xg_for"].map("{:.1f}".format)
    fixtures["level"] = pd.qcut(fixtures["xg_for"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    run = fixtures.groupby("team_id")["xg_for"].sum()
    run_label, run_format, ascending = "Total xG", "%.1f", False
elif view == "defence":
    fixtures["cell"] = fixtures["label"] + " " + fixtures["cs_prob"].map("{:.0%}".format)
    fixtures["level"] = pd.qcut(fixtures["cs_prob"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    run = fixtures.groupby("team_id")["cs_prob"].mean() * 100
    run_label, run_format, ascending = "Avg clean-sheet %", "%.0f%%", False
else:
    fixtures["cell"] = fixtures["label"] + " · " + fixtures["difficulty"].astype(str)
    fixtures["level"] = fixtures["difficulty"]
    run = fixtures.groupby("team_id")["difficulty"].mean()
    run_label, run_format, ascending = "Avg difficulty", "%.1f", True

columns = [f"GW{gameweek}" for gameweek in gameweeks]
cells = fixtures.groupby(["team_id", "gw"]).agg(cell=("cell", " + ".join), level=("level", "max")).reset_index()
labels = cells.pivot(index="team_id", columns="gw", values="cell").reindex(columns=gameweeks).fillna("Blank")
levels = cells.pivot(index="team_id", columns="gw", values="level").reindex(columns=gameweeks)
labels.columns = levels.columns = columns
teams = league.teams.set_index("id")
grid = labels.assign(team=teams["name"], run=run).sort_values("run", ascending=ascending)
levels = levels.reindex(grid.index)
styled = grid[["team", "run", *columns]].style.apply(lambda frame: levels.map(difficulty_style).reindex(columns=frame.columns).fillna(""), axis=None)
st.dataframe(
    styled,
    hide_index=True,
    height="content",
    column_config={
        "team": st.column_config.TextColumn("Team", pinned=True),
        "run": st.column_config.NumberColumn(run_label, format=run_format),
        **{column: st.column_config.TextColumn(column) for column in columns},
    },
)
legend = " ".join(f":{DIFFICULTY_BADGE_COLORS[level]}-badge[{level} {DIFFICULTY_LABELS[level].lower()}]" for level in range(1, 6))
st.markdown(f"Colour scale: {legend}")
st.caption("Attack and defence views rank every fixture in the window into five equal bands. Doubles show both opponents; blanks mean no match that gameweek.")
