from __future__ import annotations

import streamlit as st

from dashboard import ui
from dashboard.components import fixture_run_text, render_pitch
from dashboard.data import load_projections
from fpl_data.recommendations import suggest_lineup, validate_squad

manager = ui.require_manager()
projections = load_projections()
next_gw = projections.gameweeks[0] if projections.gameweeks else None

st.title("My team")
st.caption(f"{manager.team_name} · {manager.name} · GW{manager.gameweek}: {manager.event_points} pts · {manager.total_points:,} total points")

with st.container(horizontal=True):
    st.metric("Overall rank", f"{manager.rank:,}" if manager.rank else "—", border=True)
    st.metric("Team value", ui.money(manager.team_value), border=True)
    st.metric("In the bank", ui.money(manager.bank), border=True)
    st.metric(f"GW{manager.gameweek} points", manager.event_points, border=True)

if not all(validate_squad(manager.squad).values()):
    st.warning("FPL returned an incomplete or invalid 15-player squad.", icon=":material/warning:")

summary = projections.players.set_index("id")
squad = manager.squad.join(summary[["xp_next", "xmins_next", "availability_note"]], on="id")
next_fixtures = projections.team_fixtures[projections.team_fixtures["gw"] == next_gw]
squad["next_fixture"] = [fixture_run_text(next_fixtures[next_fixtures["team_id"] == team_id], [next_gw]) if next_gw else "" for team_id in squad["team_id"]]

views = {"projection": f"GW{next_gw} projection", "points": f"GW{manager.gameweek} points"} if next_gw else {"points": f"GW{manager.gameweek} points"}
view = st.segmented_control("Show on pitch", list(views), default=next(iter(views)), required=True, format_func=views.get, key="team_view")
st.html(render_pitch(squad, next_gw if view == "projection" else manager.gameweek, mode=view))

if next_gw:
    lineup = suggest_lineup(squad, squad.set_index("id")["xp_next"].to_dict())
    names = squad.set_index("id")["web_name"]
    current_captain = squad.loc[squad["is_captain"] == True, "web_name"]
    st.caption(
        f"Projection suggests {lineup['formation']} with **{names.get(lineup['captain'], '—')}** as captain "
        f"({summary.loc[lineup['captain'], 'xp_next']:.1f} xP) for GW{next_gw}, worth {lineup['xi_points']:.1f} pts. "
        f"Your last captain: {current_captain.iloc[0] if not current_captain.empty else '—'}."
    )

st.subheader("Squad details")
details = squad.assign(
    player=[f"{name} (C)" if captain else f"{name} (V)" if vice else name for name, captain, vice in zip(squad["web_name"], squad["is_captain"], squad["is_vice_captain"])],
    role=squad["squad_pos"].map(lambda position: "Starting XI" if position <= 11 else f"Bench {position - 11}"),
    price=squad["now_cost"] / 10,
    sale=squad["selling_price"] / 10,
    news=squad["availability_note"].fillna(""),
)
st.dataframe(
    details[["player", "team_short", "position", "role", "event_points", "price", "sale", "next_fixture", "xp_next", "xmins_next", "status_label", "news"]],
    hide_index=True,
    height="content",
    column_config={
        "player": st.column_config.TextColumn("Player", pinned=True),
        "team_short": st.column_config.TextColumn("Club"),
        "position": st.column_config.TextColumn("Pos."),
        "role": st.column_config.TextColumn("Line-up"),
        "event_points": st.column_config.NumberColumn(f"GW{manager.gameweek} pts"),
        "price": st.column_config.NumberColumn("Market price", format="£%.1fm"),
        "sale": st.column_config.NumberColumn("Your sale price", format="£%.1fm", help="FPL keeps half of any price rise, rounded down."),
        "next_fixture": st.column_config.TextColumn(f"GW{next_gw}" if next_gw else "Next"),
        "xp_next": st.column_config.NumberColumn("xP", format="%.1f", help="Projected points next gameweek."),
        "xmins_next": st.column_config.NumberColumn("xMins", format="%.0f", help="Expected minutes next gameweek."),
        "status_label": st.column_config.TextColumn("Status"),
        "news": st.column_config.TextColumn("News"),
    },
)
