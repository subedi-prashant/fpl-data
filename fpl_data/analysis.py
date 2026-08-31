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


# ============================================================================
# Manager / Personal Account Analysis
# ============================================================================


def load_manager_profile(db_path: Path, manager_id: int) -> dict | None:
    """Load manager profile info (name, rank, team value, total points)."""
    con = _connect(db_path)
    cursor = con.cursor()
    cursor.execute(
        "SELECT manager_id, name, team_name, team_value, bank, total_points, rank, season FROM user_profile WHERE manager_id = ?",
        (manager_id,),
    )
    row = cursor.fetchone()
    con.close()
    if not row:
        return None
    return {
        "manager_id": row[0],
        "name": row[1],
        "team_name": row[2],
        "team_value": row[3] / 10.0,  # Convert to £m
        "bank": row[4] / 10.0,
        "total_points": row[5],
        "rank": row[6],
        "season": row[7],
    }


def load_manager_picks(db_path: Path, manager_id: int, season: int) -> pd.DataFrame:
    """Load all team picks for a manager in a season, with player details."""
    con = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT
            ut.manager_id, ut.season, ut.gameweek, ut.player_id,
            p.web_name, t.short_name AS team,
            p.element_type, ut.position AS squad_pos, ut.is_captain, ut.is_vice_captain,
            ut.points, ut.multiplier
        FROM user_team ut
        JOIN players p ON ut.player_id = p.id
        JOIN teams t ON p.team_id = t.id
        WHERE ut.manager_id = ? AND ut.season = ?
        ORDER BY ut.gameweek, ut.position
        """,
        con,
        params=(manager_id, season),
    )
    con.close()
    if df.empty:
        return df
    df["position"] = df["element_type"].map(_POSITION_MAP)  # "GKP"/"DEF"/etc.
    return df


def load_manager_transfers(db_path: Path, manager_id: int, season: int) -> pd.DataFrame:
    """Load all transfers for a manager in a season with player details."""
    con = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT
            ut.manager_id, ut.season, ut.gameweek,
            ut.player_out_id, pout.web_name AS player_out,
            ut.player_in_id, pin.web_name AS player_in,
            ut.entry_cost, ut.cost_change_event
        FROM user_transfers ut
        JOIN players pout ON ut.player_out_id = pout.id
        JOIN players pin ON ut.player_in_id = pin.id
        WHERE ut.manager_id = ? AND ut.season = ?
        ORDER BY ut.gameweek
        """,
        con,
        params=(manager_id, season),
    )
    con.close()
    return df


def load_manager_history(db_path: Path, manager_id: int) -> pd.DataFrame:
    """Load season-by-season history for a manager."""
    con = _connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT
            manager_id, season, total_points, rank, transfers_used, finished
        FROM user_history
        WHERE manager_id = ?
        ORDER BY season DESC
        """,
        con,
        params=(manager_id,),
    )
    con.close()
    return df


def transfer_quality_analysis(
    db_path: Path,
    manager_id: int,
    season: int,
) -> pd.DataFrame:
    """
    Analyze quality of transfers: for each transfer, compute points gained/lost
    by the incoming vs outgoing player in the gameweeks after the transfer.
    Returns DataFrame with transfer details and estimated impact.
    """
    transfers = load_manager_transfers(db_path, manager_id, season)
    if transfers.empty:
        return transfers

    history = load_player_history(db_path)

    # For each transfer, find player performance in next 3 gameweeks
    results = []
    for _, t in transfers.iterrows():
        gw = int(t["gameweek"])
        player_out_id = int(t["player_out_id"])
        player_in_id = int(t["player_in_id"])

        # Points in gameweeks after transfer (gw, gw+1, gw+2)
        future_gws = [gw, gw + 1, gw + 2]
        out_hist = history[(history["player_id"] == player_out_id) & (history["round"].isin(future_gws))]
        in_hist = history[(history["player_id"] == player_in_id) & (history["round"].isin(future_gws))]

        points_out = out_hist["total_points"].sum() if not out_hist.empty else 0
        points_in = in_hist["total_points"].sum() if not in_hist.empty else 0
        net_gain = points_in - points_out

        results.append({
            "gameweek": gw,
            "player_out": t["player_out"],
            "player_in": t["player_in"],
            "cost": t["entry_cost"] / 10.0,
            "points_out_3gw": points_out,
            "points_in_3gw": points_in,
            "net_gain": net_gain,
            "quality": "Good" if net_gain >= 5 else "Okay" if net_gain >= 0 else "Poor",
        })

    return pd.DataFrame(results).reset_index(drop=True)


def captaincy_analysis(
    db_path: Path,
    manager_id: int,
    season: int,
) -> pd.DataFrame:
    """
    Analyze captaincy choices: compare points scored by chosen captain vs
    best available captain in the squad for each gameweek.
    """
    picks = load_manager_picks(db_path, manager_id, season)
    if picks.empty:
        return picks

    all_history = load_player_history(db_path)  # load once, filter per GW
    results = []
    for gw in picks["gameweek"].unique():
        gw_picks = picks[picks["gameweek"] == gw]
        gw_history = all_history[all_history["round"] == gw]

        # Find chosen captain and their points (with 2x multiplier)
        captain = gw_picks[gw_picks["is_captain"] == 1]
        if captain.empty:
            continue
        captain_id = captain.iloc[0]["player_id"]
        captain_name = captain.iloc[0]["web_name"]
        captain_history = gw_history[gw_history["player_id"] == captain_id]
        captain_points = captain_history["total_points"].iloc[0] * 2 if not captain_history.empty else 0

        # element_type 1 = GKP; exclude from captaincy candidates
        squad_player_ids = gw_picks[gw_picks["element_type"] != 1]["player_id"].unique()
        squad_gw_history = gw_history[gw_history["player_id"].isin(squad_player_ids)]
        if squad_gw_history.empty:
            continue
        best_captain = squad_gw_history.nlargest(1, "total_points").iloc[0]
        best_captain_points = best_captain["total_points"] * 2
        best_captain_name = best_captain["web_name"]

        results.append({
            "gameweek": gw,
            "chosen_captain": captain_name,
            "chosen_points": captain_points,
            "best_possible": best_captain_name,
            "best_possible_points": best_captain_points,
            "opportunity_cost": best_captain_points - captain_points,
            "decision_quality": "Optimal" if captain_id == best_captain["player_id"] else "Suboptimal",
        })

    return pd.DataFrame(results).reset_index(drop=True)


def bench_impact(
    db_path: Path,
    manager_id: int,
    season: int,
) -> pd.DataFrame:
    """
    Analyze points left on bench: for each gameweek, show how many points
    the top substitute on the bench scored.
    """
    picks = load_manager_picks(db_path, manager_id, season)
    if picks.empty:
        return picks

    all_history = load_player_history(db_path)  # load once, filter per GW
    results = []
    for gw in picks["gameweek"].unique():
        gw_picks = picks[picks["gameweek"] == gw]
        gw_history = all_history[all_history["round"] == gw]

        # squad_pos 12-15 = bench
        starters = gw_picks[gw_picks["squad_pos"] < 12]
        bench = gw_picks[gw_picks["squad_pos"] >= 12]

        if bench.empty:
            continue

        # Find highest scorer on bench
        bench_player_ids = bench["player_id"].tolist()
        bench_gw_history = gw_history[gw_history["player_id"].isin(bench_player_ids)]
        if bench_gw_history.empty:
            continue
        best_bench = bench_gw_history.nlargest(1, "total_points").iloc[0]

        results.append({
            "gameweek": gw,
            "best_on_bench": best_bench["web_name"],
            "bench_points": best_bench["total_points"],
            "position": best_bench["position"],  # 12=first sub, 13=second sub, etc.
            "missed_opportunity": "Yes" if best_bench["total_points"] >= 8 else "No",
        })

    return pd.DataFrame(results).reset_index(drop=True)


def vs_average_performance(
    db_path: Path,
    manager_id: int,
    season: int,
) -> dict:
    """
    Compare manager's performance vs league average (from gameweeks table).
    Returns summary dict with manager points, rank, and comparison stats.
    """
    history = load_manager_history(db_path, manager_id)
    season_history = history[history["season"] == season]
    if season_history.empty:
        return {}

    row = season_history.iloc[0]
    manager_points = row["total_points"]
    manager_rank = row["rank"]

    # Get league average from gameweeks
    con = _connect(db_path)
    cursor = con.cursor()
    cursor.execute("SELECT AVG(average_entry_score) FROM gameweeks")
    avg_points = cursor.fetchone()[0] or 0
    con.close()

    # Rough estimate of average rank (lower rank is better, assuming ~1M teams)
    estimated_avg_rank = 500000

    return {
        "manager_points": manager_points,
        "league_avg_points": round(avg_points, 1),
        "points_above_average": manager_points - avg_points,
        "manager_rank": manager_rank or "N/A",
        "estimated_rank_percentile": (manager_rank / estimated_avg_rank * 100) if manager_rank else None,
        "season": season,
    }


def optimal_team_suggestion(
    db_path: Path,
    manager_id: int,
    gameweek: int,
    budget: float = 100.0,
) -> pd.DataFrame:
    """
    Suggest an optimal team (11 players + bench) within a budget,
    based on form, fixture difficulty, and recent points.
    Simple heuristic: prioritize high form + low fixture difficulty.
    """
    players = load_players(db_path)
    fixtures = load_fixtures(db_path)
    history = load_player_history(db_path)

    # Get next gameweek fixture difficulty
    next_fixtures = fixtures[fixtures["event"] == gameweek]
    if next_fixtures.empty:
        # If future GW not in fixtures, use current form as proxy
        team_difficulty = {team: 3 for team in players["team"].unique()}
    else:
        team_difficulty = {}
        for _, f in next_fixtures.iterrows():
            team_difficulty[f["team_h_short"]] = f["team_h_difficulty"]
            team_difficulty[f["team_a_short"]] = f["team_a_difficulty"]

    # Compute average recent points (last 3 gameweeks) for each player
    recent_history = history[history["round"] >= gameweek - 3]
    recent_avg = recent_history.groupby("player_id")["total_points"].mean()

    players["avg_recent_points"] = players["id"].map(recent_avg).fillna(players["points_per_game"])
    players["difficulty_next"] = players["team_short"].map(team_difficulty).fillna(3)

    # Score: high form + low difficulty = better pick
    players["pick_score"] = (
        players["avg_recent_points"] * 2 +
        players["form"].astype(float) +
        (5 - players["difficulty_next"])  # Lower difficulty = higher score
    )

    # Build team within budget constraints
    selected = []
    remaining_budget = budget
    for position in ["GKP", "DEF", "MID", "FWD"]:
        pos_players = players[players["position"] == position].sort_values("pick_score", ascending=False)
        # Simple greedy: take best available within budget
        for _, p in pos_players.iterrows():
            if len([s for s in selected if s["position"] == position]) < (
                1 if position == "GKP" else 5 if position in ["DEF", "MID"] else 3
            ):
                if p["cost_m"] <= remaining_budget:
                    selected.append(p.to_dict())
                    remaining_budget -= p["cost_m"]

    result = pd.DataFrame(selected) if selected else pd.DataFrame()
    return result[["web_name", "team_short", "position", "cost_m", "form", "avg_recent_points", "pick_score"]].reset_index(drop=True) if not result.empty else result
