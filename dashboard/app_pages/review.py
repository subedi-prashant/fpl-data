from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import ui
from dashboard.data import load_league

manager = ui.require_manager()
league = load_league()

st.title("Decision review")
st.caption(f"{manager.team_name} · Public gameweek history and completed transfers this season.")

history = pd.DataFrame(manager.history.get("current", []))
if history.empty:
    st.info("No gameweek history yet. It appears after your first deadline.", icon=":material/info:")
else:
    with st.container(horizontal=True):
        st.metric("Transfers made", int(history["event_transfers"].sum()), border=True)
        st.metric("Points spent on hits", int(history["event_transfers_cost"].sum()), border=True)
        st.metric("Points left on bench", int(history["points_on_bench"].sum()), border=True)
        st.metric("Average per gameweek", f"{history['points'].mean():.1f}", border=True)
    averages = league.gameweeks.set_index("id")["average_entry_score"]
    chart = history[["event", "points"]].assign(average=history["event"].map(averages)).rename(columns={"event": "Gameweek", "points": "Your points", "average": "FPL average"})
    st.line_chart(chart, x="Gameweek", y=["Your points", "FPL average"], color=["#37003C", "#98A2B3"], y_label="Points")
    table = history[["event", "points", "total_points", "overall_rank", "bank", "value", "event_transfers", "event_transfers_cost", "points_on_bench"]].assign(
        bank=history["bank"] / 10,
        value=history["value"] / 10,
    )
    st.dataframe(
        table.sort_values("event", ascending=False),
        hide_index=True,
        column_config={
            "event": st.column_config.NumberColumn("GW"),
            "points": st.column_config.NumberColumn("Points"),
            "total_points": st.column_config.NumberColumn("Total"),
            "overall_rank": st.column_config.NumberColumn("Overall rank", format="localized"),
            "bank": st.column_config.NumberColumn("Bank", format="£%.1fm"),
            "value": st.column_config.NumberColumn("Team value", format="£%.1fm"),
            "event_transfers": st.column_config.NumberColumn("Transfers"),
            "event_transfers_cost": st.column_config.NumberColumn("Hit cost"),
            "points_on_bench": st.column_config.NumberColumn("Bench pts"),
        },
    )

chips = pd.DataFrame(manager.history.get("chips", []))
if not chips.empty:
    labels = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}
    st.caption("Chips played: " + ", ".join(f"{labels.get(chip.name, chip.name)} (GW{chip.event})" for chip in chips.itertuples()))

st.subheader("Transfer history")
transfers = pd.DataFrame(manager.transfers)
if transfers.empty:
    st.caption("No completed transfers this season.")
else:
    names = league.players.set_index("id")["web_name"]
    st.dataframe(
        transfers.assign(
            sold=transfers["element_out"].map(names),
            bought=transfers["element_in"].map(names),
            sale_price=transfers["element_out_cost"] / 10,
            buy_price=transfers["element_in_cost"] / 10,
            time=pd.to_datetime(transfers["time"], utc=True, errors="coerce"),
        )[["event", "sold", "sale_price", "bought", "buy_price", "time"]],
        hide_index=True,
        height="content",
        column_config={
            "event": st.column_config.NumberColumn("GW"),
            "sold": st.column_config.TextColumn("Sold"),
            "sale_price": st.column_config.NumberColumn("Sale", format="£%.1fm"),
            "bought": st.column_config.TextColumn("Bought"),
            "buy_price": st.column_config.NumberColumn("Cost", format="£%.1fm"),
            "time": st.column_config.DatetimeColumn("Completed", format="D MMM, HH:mm"),
        },
    )
