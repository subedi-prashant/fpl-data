from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from dashboard import ui
from dashboard.components import fixture_badges, fixture_run_text, heat_style, move_reasons, status_badge
from dashboard.data import CACHE_TTL, load_league, load_projections
from fpl_data.recommendations import FREE_TRANSFER_VALUE, PlannerSettings, plan_transfers, suggest_lineup, validate_squad

PROJECTION_COLUMNS = ["xp_next", "xmins_next", "availability_next", "availability_note", "return_date", "recent_points", "xgi90_recent", "xp_window", "xp_window_list"]
PLANNER_COLUMNS = ["id", "web_name", "team_id", "team_short", "position", "now_cost", "status"]


@st.cache_resource(ttl=CACHE_TTL, max_entries=64, show_spinner="Searching every legal transfer…")
def run_planner(squad: pd.DataFrame, players: pd.DataFrame, xp: pd.DataFrame, bank: int, settings: PlannerSettings, position: str | None, required_out: int | None):
    return plan_transfers(squad, players, xp, bank, settings, position=position, required_out=required_out)


def player_panel(player: pd.Series, gameweeks: list[int], team_fixtures: pd.DataFrame, price_label: str, price: int) -> None:
    with st.container(border=True):
        st.markdown(f"**{player['web_name']}** · {player['team_short']} {player['position']} · {price_label} {ui.money(price)}")
        st.markdown(status_badge(player))
        if player["status"] != "a" and player.get("availability_note"):
            st.caption(player["availability_note"])
        st.markdown(fixture_badges(team_fixtures[team_fixtures["team_id"] == player["team_id"]], gameweeks))
        recent = list(player["recent_points"])
        st.markdown(
            f"Projected {ui.gameweek_span(gameweeks)}: **{player['xp_window']:.1f} pts** · "
            f"Expected minutes: **{player['xmins_next']:.0f}**"
        )
        st.caption(f"Last {len(recent)} GWs: {' · '.join(map(str, recent))} ({sum(recent)} pts)" if recent else "No minutes this season yet.")


def comparison_chart(out_players: pd.DataFrame, in_players: pd.DataFrame, gameweeks: list[int]) -> alt.Chart:
    rows = []
    for side, players in (("Sell", out_players), ("Buy", in_players)):
        for gameweek in gameweeks:
            rows.append({"Gameweek": f"GW{gameweek}", "Move": side, "Projected points": float(players[f"xp_gw{gameweek}"].sum())})
    return (
        alt.Chart(pd.DataFrame(rows), title="Projected points per gameweek")
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("Gameweek:N", sort=[f"GW{gameweek}" for gameweek in gameweeks], title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("Move:N", sort=["Sell", "Buy"]),
            y=alt.Y("Projected points:Q", title="Projected points"),
            color=alt.Color("Move:N", sort=["Sell", "Buy"], scale=alt.Scale(range=["#98A2B3", "#008A55"]), legend=alt.Legend(orient="top", title=None)),
            tooltip=["Gameweek", "Move", alt.Tooltip("Projected points:Q", format=".1f")],
        )
        .properties(height=220)
    )


def render_move(move: pd.Series, summary: pd.DataFrame, squad: pd.DataFrame, gameweeks: list[int], team_fixtures: pd.DataFrame, recommended: bool) -> None:
    out_players = summary.loc[list(move["out_ids"])]
    in_players = summary.loc[list(move["in_ids"])]
    selling = squad.set_index("id")["selling_price"]
    with st.container(border=True, key="hero-move"):
        if recommended:
            st.badge("Recommended move", icon=":material/recommend:", color="green")
        else:
            st.badge("Selected alternative", icon=":material/compare_arrows:", color="blue")
        st.subheader("  ·  ".join(f"{out_name} → {in_name}" for out_name, in_name in zip(out_players["web_name"], in_players["web_name"])))
        transfer_cost = "Free" if move["hits"] == 0 else f"−{int(move['hit_cost'])} pts"
        with st.container(horizontal=True):
            st.metric(
                "Projected gain",
                f"{move['points_gain']:+.1f} pts",
                help=f"Change in your best XI + captain (plus a small bench weighting) over {ui.gameweek_span(gameweeks)}, after any hit.",
                border=True,
            )
            st.metric("Transfer cost", transfer_cost, help="Each transfer beyond your free transfers costs 4 points.", border=True)
            st.metric("Bank after", ui.money(move["bank_after"]), border=True)
            st.metric(
                "Decision value",
                f"{move['net_gain']:+.1f}",
                help=f"Gain with nearer gameweeks weighted more, minus hits and the value of a saved free transfer (≈{FREE_TRANSFER_VALUE} pts). Positive means worth doing now.",
                border=True,
            )
        sell_column, buy_column = st.columns(2)
        with sell_column:
            st.markdown("**:material/logout: Sell**")
            for player_id, player in out_players.iterrows():
                player_panel(player, gameweeks, team_fixtures, "sale", int(selling.get(player_id, player["now_cost"])))
        with buy_column:
            st.markdown("**:material/login: Buy**")
            for _, player in in_players.iterrows():
                player_panel(player, gameweeks, team_fixtures, "cost", int(player["now_cost"]))
        if len(gameweeks) > 1:
            st.altair_chart(comparison_chart(out_players, in_players, gameweeks))
        st.markdown("**Why this move**")
        st.markdown("\n".join(f"- {reason}" for reason in move_reasons(out_players, in_players, team_fixtures, len(gameweeks))))
        st.caption(
            f"Budget check: {ui.money(move['selling_price'])} sale value + {ui.money(move['available_budget'] - move['selling_price'])} bank "
            f"= {ui.money(move['available_budget'])} available, incoming cost {ui.money(move['incoming_cost'])}. "
            "Same position, max 3 per club and squad shape are all checked."
        )


manager = ui.require_manager()
league = load_league()
projections = load_projections()

st.title("Transfer planner")
st.caption(f"{manager.team_name} · Ranked by projected points from upcoming fixtures, player form, minutes and injury news.")

if not projections.gameweeks:
    st.info("There are no upcoming gameweeks to plan for.", icon=":material/event_busy:")
    st.stop()
if not all(validate_squad(manager.squad).values()):
    st.error("Recommendations are paused because FPL returned an incomplete 15-player squad. Try Refresh data.", icon=":material/error:")
    st.stop()

summary = projections.players
next_gw = projections.gameweeks[0]
squad = manager.squad.merge(ui.with_window_xp(summary, projections.gameweeks)[["id", *PROJECTION_COLUMNS[:-2]]], on="id", how="left")
lineup = suggest_lineup(squad, squad.set_index("id")["xp_next"].to_dict())

deadline = league.next_deadline
deadline_text = "—"
if deadline is not None and not pd.isna(deadline):
    timezone = st.context.timezone or "UTC"
    try:
        deadline_text = deadline.tz_convert(timezone).strftime("%a %d %b, %H:%M")
    except (TypeError, ValueError, KeyError):
        deadline_text = deadline.strftime("%a %d %b, %H:%M UTC")
with st.container(horizontal=True):
    st.metric(f"GW{next_gw} deadline", deadline_text, help="Shown in your browser's time zone.", border=True)
    st.metric("In the bank", ui.money(manager.bank), border=True)
    st.metric(
        "Free transfers",
        manager.free_transfers,
        help="Rebuilt from your public transfer history (one per gameweek, max five, kept on Wildcard/Free Hit). Transfers already made for the next deadline aren't public.",
        border=True,
    )
    st.metric(f"Projected GW{next_gw}", f"{lineup['xi_points']:.1f} pts", help="Your best starting XI for next gameweek, captain counted twice.", border=True)

flagged = squad[squad["status"] != "a"].sort_values("squad_pos")
if not flagged.empty:
    with st.container(border=True):
        st.markdown(f"**:material/medical_services: {len(flagged)} flagged player{'s' if len(flagged) != 1 else ''} in your squad**")
        for _, player in flagged.iterrows():
            note = player.get("availability_note") or player.get("status_label")
            st.markdown(f"{status_badge(player)} **{player['web_name']}** ({player['team_short']}) · {note}")

with st.container(border=True):
    st.markdown("**Plan settings**")
    with st.container(horizontal=True, gap="medium"):
        horizon = st.segmented_control(
            "Plan over",
            ui.HORIZON_OPTIONS,
            default=ui.DEFAULT_HORIZON,
            required=True,
            format_func=lambda gameweeks: f"{gameweeks} GW" if gameweeks == 1 else f"{gameweeks} GWs",
            key="planner_horizon",
            help="Longer windows reward good fixture runs. Nearer gameweeks still count more because projections get less certain.",
        )
        free_transfers = st.segmented_control(
            "Free transfers",
            [1, 2, 3, 4, 5],
            default=manager.free_transfers,
            required=True,
            key=f"planner_free_transfers_{manager.manager_id}",
            help="Detected from your history. Change it if you've already made transfers this week.",
        )
        max_transfers = st.segmented_control(
            "Moves to consider",
            [1, 2],
            default=2 if free_transfers >= 2 else 1,
            required=True,
            format_func=lambda moves: "1 transfer" if moves == 1 else "Up to 2",
            key=f"planner_moves_{free_transfers}",
            help="Two-transfer combinations are searched together, so budget and the club limit are checked across both moves.",
        )
        position = st.segmented_control("Position", ["All", "GKP", "DEF", "MID", "FWD"], default="All", required=True, key="planner_position")
    with st.expander("More options", icon=":material/tune:"):
        sell_pool = squad if position == "All" else squad[squad["position"] == position]
        sell_names = sell_pool.set_index("id")["web_name"].to_dict()
        required_out = st.selectbox(
            "Player to sell",
            [0, *sell_pool["id"].astype(int)],
            format_func=lambda player_id: "Any player (best move across the squad)" if player_id == 0 else sell_names[player_id],
            key="planner_required_out",
        )
        include_doubtful = st.toggle(
            "Consider doubtful players to buy",
            value=False,
            key="planner_include_doubtful",
            help="Doubtful players are already discounted by their chance of playing. Injured, suspended and unavailable players are never suggested.",
        )

gameweeks = ui.window(projections, int(horizon))
summary_window = ui.with_window_xp(summary, gameweeks).set_index("id", drop=False)
team_fixtures = ui.team_runs(projections, gameweeks)
settings = PlannerSettings(
    free_transfers=int(free_transfers),
    max_transfers=int(max_transfers),
    allowed_statuses=frozenset({"a", "d"}) if include_doubtful else frozenset({"a"}),
)
plan = run_planner(
    manager.squad[[*PLANNER_COLUMNS, "selling_price"]],
    summary[PLANNER_COLUMNS],
    projections.xp_matrix()[gameweeks],
    manager.bank,
    settings,
    None if position == "All" else position,
    int(required_out) or None,
)

if plan.moves.empty:
    st.info("No legal transfer fits your budget, position and club-limit rules with these settings.", icon=":material/search_off:")
    st.stop()

options = plan.moves if required_out else plan.moves.drop_duplicates("out_ids")
options = options.head(12).reset_index(drop=True)
best = plan.best
if best is None:
    top = options.iloc[0]
    with st.container(border=True, key="hold-move"):
        st.badge("Best decision", icon=":material/pause_circle:", color="gray")
        st.subheader("Roll your free transfer")
        st.write(
            f"No move beats the value of saving a free transfer (≈{FREE_TRANSFER_VALUE} pts) over {ui.gameweek_span(gameweeks)}. "
            f"The best option, **{top['player_out']} → {top['player_in']}**, changes your projection by **{top['points_gain']:+.1f} pts**."
        )
        if int(free_transfers) >= 5:
            st.caption("You're at the five free transfer cap, so any positive move is free value. Consider the options below.")

st.subheader("Options")
st.caption("Select a row to inspect the move. Sorted by decision value; each outgoing player appears once unless you pick a player to sell.")
incoming = [summary_window.loc[list(ids)] for ids in options["in_ids"]]
table = options.assign(
    sell=options["player_out"],
    buy=options["player_in"],
    cost=options["incoming_cost"] / 10,
    bank=options["bank_after"] / 10,
    fixtures=[" | ".join(fixture_run_text(team_fixtures[team_fixtures["team_id"] == team_id], gameweeks[:3]) for team_id in players["team_id"]) for players in incoming],
    form=[players["recent_points"].iloc[0] if len(players) == 1 else [] for players in incoming],
    status=[" / ".join(players["status_label"]) for players in incoming],
)
selection = st.dataframe(
    table[["sell", "buy", "position", "cost", "bank", "points_gain", "net_gain", "fixtures", "form", "status"]],
    hide_index=True,
    height="content",
    on_select="rerun",
    selection_mode="single-row",
    key="planner_options",
    column_config={
        "sell": st.column_config.TextColumn("Sell", pinned=True),
        "buy": st.column_config.TextColumn("Buy"),
        "position": st.column_config.TextColumn("Pos."),
        "cost": st.column_config.NumberColumn("Cost", format="£%.1fm"),
        "bank": st.column_config.NumberColumn("Bank after", format="£%.1fm"),
        "points_gain": st.column_config.NumberColumn("Gain", format="%+.1f pts", help=f"Projected points gained over {ui.gameweek_span(gameweeks)} after hits."),
        "net_gain": st.column_config.NumberColumn("Decision value", format="%+.1f", help="Weighted gain minus hits and the value of a saved free transfer."),
        "fixtures": st.column_config.TextColumn("Next 3 fixtures (buy)"),
        "form": st.column_config.BarChartColumn("Last 5 GWs", y_min=0, y_max=15, help="Actual points of the incoming player."),
        "status": st.column_config.TextColumn("Status"),
    },
)
selected_rows = [row for row in selection.selection.rows if row < len(options)]
selected = options.iloc[selected_rows[0]] if selected_rows else best
if selected is not None:
    is_best = best is not None and selected["out_ids"] == best["out_ids"] and selected["in_ids"] == best["in_ids"]
    render_move(selected, summary_window, manager.squad, gameweeks, team_fixtures, recommended=is_best)

st.subheader(f"Your squad, {ui.gameweek_span(gameweeks)}")
roles = {player_id: "Captain" if player_id == lineup["captain"] else "Starter" for player_id in lineup["starting"]}
roles.update({player_id: f"Bench {order}" for order, player_id in enumerate(lineup["bench"], start=1)})
planner_table = squad.assign(
    role=squad["id"].map(roles),
    sale=squad["selling_price"] / 10,
    fixtures=[fixture_run_text(team_fixtures[team_fixtures["team_id"] == team_id], gameweeks[:3]) for team_id in squad["team_id"]],
)
xp_columns = {f"xp_gw{gameweek}": f"GW{gameweek}" for gameweek in gameweeks}
planner_table = planner_table.join(summary_window[list(xp_columns)], on="id")
planner_table["total"] = planner_table[list(xp_columns)].sum(axis=1)
planner_table = planner_table.sort_values(["squad_pos"])
st.dataframe(
    planner_table[["web_name", "position", "team_short", "role", "status_label", "sale", *xp_columns, "total", "fixtures"]]
    .style.map(lambda value: heat_style(value, 8.0), subset=list(xp_columns))
    .map(lambda value: heat_style(value, 8.0 * len(gameweeks)), subset=["total"]),
    hide_index=True,
    height="content",
    column_config={
        "web_name": st.column_config.TextColumn("Player", pinned=True),
        "position": st.column_config.TextColumn("Pos."),
        "team_short": st.column_config.TextColumn("Club"),
        "role": st.column_config.TextColumn(f"GW{next_gw} role", help="Suggested from projections: best formation, captain and bench order."),
        "status_label": st.column_config.TextColumn("Status"),
        "sale": st.column_config.NumberColumn("Sale price", format="£%.1fm"),
        **{column: st.column_config.NumberColumn(label, format="%.1f") for column, label in xp_columns.items()},
        "total": st.column_config.NumberColumn("Total", format="%.1f"),
        "fixtures": st.column_config.TextColumn("Next 3 fixtures"),
    },
)
st.caption(
    f"Suggested GW{next_gw} line-up: {lineup['formation']}, captain "
    f"{summary_window.loc[lineup['captain'], 'web_name'] if lineup['captain'] else '—'}. "
    "Squad shown as of your last deadline; moves already made for the next deadline aren't public."
)

with st.expander("How recommendations are made", icon=":material/calculate:"):
    st.markdown(
        """
**Projected points (xP)** are built per fixture, the way public FPL models such as AIrsenal and the open-source FPL solvers work:

- **Fixtures**: a Poisson team model rates every club's attack and defence (with home advantage) from this season's expected goals and results. That gives expected goals for and against in each match, clean-sheet odds and the 1–5 difficulty shown on badges. Blank and double gameweeks are handled automatically.
- **Form**: each player's expected goals, assists, saves, defensive actions and bonus per 90 minutes, weighted toward recent gameweeks and blended with a price-based prior so a few big games don't dominate.
- **Minutes**: start probability and minutes from recent appearances, so rotation risks score lower.
- **Injuries**: FPL's status, chance of playing and the "Expected back" or "Suspended until" date in the news. Injured players score zero until their return, then ramp up.
- **Scoring**: current FPL rules, read live from the game (appearance, goals, assists, clean sheets, goals conceded, saves, defensive contributions, bonus, cards).

**Transfers**: every legal one- or two-transfer move is scored on your best XI each gameweek, captain counted twice, plus a small bench weighting. Nearer gameweeks count more (×0.84 per week). Hits cost 4 points, and a move must beat the value of saving a free transfer to be recommended.

Validated with a walk-forward backtest against the previous formula. Run `fpl-data backtest` to reproduce it.
"""
    )
