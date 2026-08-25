"""Analysis functions for FPL data using pandas."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


# Position labels
_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def load_players(db_path: Path) -> pd.DataFrame:
    """Load players joined with team names from the DB."""
    con = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT
            p.id,
            p.web_name,
            p.first_name || ' ' || p.second_name AS full_name,
            t.name AS team,
            t.short_name AS team_short,
            p.element_type,
            p.now_cost,
            p.total_points,
            p.minutes,
            p.goals_scored,
            p.assists,
            p.clean_sheets,
            p.selected_by_percent,
            p.status,
            p.form,
            p.points_per_game
        FROM players p
        JOIN teams t ON p.team_id = t.id
        """,
        con,
    )
    con.close()

    df["position"] = df["element_type"].map(_POSITION_MAP)
    df["cost_m"] = df["now_cost"] / 10.0
    df["form"] = pd.to_numeric(df["form"], errors="coerce").fillna(0.0)
    df["points_per_game"] = pd.to_numeric(df["points_per_game"], errors="coerce").fillna(0.0)
    df["selected_by_percent"] = pd.to_numeric(df["selected_by_percent"], errors="coerce").fillna(0.0)
    # value = total points per £1m
    df["value"] = (df["total_points"] / df["cost_m"]).round(1)
    return df


def load_fixtures(db_path: Path) -> pd.DataFrame:
    """Load fixtures joined with team names."""
    con = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT
            f.id,
            f.event,
            th.name AS team_h,
            th.short_name AS team_h_short,
            ta.name AS team_a,
            ta.short_name AS team_a_short,
            f.team_h_difficulty,
            f.team_a_difficulty,
            f.team_h_score,
            f.team_a_score,
            f.finished,
            f.kickoff_time
        FROM fixtures f
        JOIN teams th ON f.team_h = th.id
        JOIN teams ta ON f.team_a = ta.id
        """,
        con,
    )
    con.close()
    return df


def load_gameweeks(db_path: Path) -> pd.DataFrame:
    con = _connect(db_path)
    df = pd.read_sql_query("SELECT * FROM gameweeks ORDER BY id", con)
    con.close()
    return df


def load_player_history(db_path: Path) -> pd.DataFrame:
    con = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT ph.*, p.web_name, p.element_type
        FROM player_history ph
        JOIN players p ON ph.player_id = p.id
        """,
        con,
    )
    con.close()
    df["position"] = df["element_type"].map(_POSITION_MAP)
    return df


def best_value_players(
    db_path: Path,
    position: str | None = None,
    min_minutes: int = 450,
    top_n: int = 20,
) -> pd.DataFrame:
    """Return top N players by value (total points per £1m), filtered optionally by position."""
    df = load_players(db_path)
    df = df[df["minutes"] >= min_minutes]
    if position:
        df = df[df["position"] == position]
    return (
        df.sort_values("value", ascending=False)
        .head(top_n)[["web_name", "team", "position", "cost_m", "total_points", "value", "form", "status"]]
        .reset_index(drop=True)
    )


def top_performers(
    db_path: Path,
    position: str | None = None,
    sort_by: str = "total_points",
    top_n: int = 20,
) -> pd.DataFrame:
    """Return top N players sorted by a given stat."""
    df = load_players(db_path)
    if position:
        df = df[df["position"] == position]
    valid_cols = {"total_points", "form", "points_per_game", "goals_scored", "assists", "cost_m"}
    sort_col = sort_by if sort_by in valid_cols else "total_points"
    return (
        df.sort_values(sort_col, ascending=False)
        .head(top_n)[["web_name", "team", "position", "cost_m", "total_points", "form", "points_per_game", "goals_scored", "assists"]]
        .reset_index(drop=True)
    )


def fixture_difficulty_heatmap(db_path: Path, next_n_gws: int = 6) -> pd.DataFrame:
    """
    Return a team × gameweek difficulty matrix for the next N gameweeks.
    Difficulty is from the team's perspective (1=easy, 5=hard).
    """
    fixtures = load_fixtures(db_path)
    gameweeks = load_gameweeks(db_path)

    current_gw = gameweeks.loc[gameweeks["is_current"] == 1, "id"]
    start_gw = int(current_gw.iloc[0]) if not current_gw.empty else 1
    gw_range = list(range(start_gw, start_gw + next_n_gws))

    upcoming = fixtures[fixtures["event"].isin(gw_range)].copy()

    rows = []
    # Home team perspective
    home = upcoming[["event", "team_h_short", "team_a_short", "team_h_difficulty"]].copy()
    home.columns = ["gw", "team", "opponent", "difficulty"]
    home["venue"] = "H"
    # Away team perspective
    away = upcoming[["event", "team_a_short", "team_h_short", "team_a_difficulty"]].copy()
    away.columns = ["gw", "team", "opponent", "difficulty"]
    away["venue"] = "A"

    combined = pd.concat([home, away], ignore_index=True)
    combined["label"] = combined["opponent"] + "(" + combined["venue"] + ")"

    pivot = combined.pivot_table(
        index="team", columns="gw", values="difficulty", aggfunc="first"
    )
    pivot.columns = [f"GW{c}" for c in pivot.columns]
    return pivot.reset_index().rename(columns={"team": "Team"})


def player_form_last_n(
    db_path: Path,
    n_gameweeks: int = 5,
    min_minutes: int = 45,
    top_n: int = 20,
) -> pd.DataFrame:
    """Return top players by average points over the last N completed gameweeks."""
    history = load_player_history(db_path)
    gameweeks = load_gameweeks(db_path)

    finished_gws = gameweeks[gameweeks["finished"] == 1]["id"]
    if finished_gws.empty:
        return pd.DataFrame()

    last_n = sorted(finished_gws.tolist())[-n_gameweeks:]
    recent = history[history["round"].isin(last_n) & (history["minutes"] >= min_minutes)]

    agg = (
        recent.groupby(["player_id", "web_name", "position"])
        .agg(
            avg_points=("total_points", "mean"),
            total_points=("total_points", "sum"),
            appearances=("total_points", "count"),
        )
        .reset_index()
    )
    return (
        agg.sort_values("avg_points", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
