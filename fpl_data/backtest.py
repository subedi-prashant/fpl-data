"""Walk-forward backtest: predict each gameweek using only data available before it."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from fpl_data import frames
from fpl_data.projections import ModelConfig, project_players, scoring_from_bootstrap

LEGACY_DIFFICULTY_MULTIPLIERS = {1: 1.18, 2: 1.09, 3: 1.0, 4: 0.91, 5: 0.82}
SEASON_TOTAL_COLUMNS = {
    "minutes": "minutes",
    "starts": "starts",
    "expected_goals": "expected_goals",
    "expected_assists": "expected_assists",
    "saves": "saves",
    "bonus": "bonus",
    "yellow_cards": "yellow_cards",
    "red_cards": "red_cards",
    "defensive_contribution": "defensive_contribution",
    "total_points": "total_points",
}


def players_as_of(players: pd.DataFrame, gameweek_stats: pd.DataFrame, gameweek: int) -> pd.DataFrame:
    """Rebuild season-to-date player attributes from gameweeks before `gameweek`.

    Historical injury flags are not published, so every player is treated as available.
    """
    before = gameweek_stats[gameweek_stats["gw"] < gameweek]
    totals = before.groupby("player_id")[list(SEASON_TOTAL_COLUMNS.values())].sum()
    snapshot = players.copy()
    for column, source in SEASON_TOTAL_COLUMNS.items():
        snapshot[column] = snapshot["id"].map(totals[source]).fillna(0.0) if not totals.empty else 0.0
    recent = before[before["gw"] >= gameweek - 4].groupby("player_id")["total_points"].mean()
    appearances = before[before["minutes"] > 0].groupby("player_id").size()
    snapshot["form"] = snapshot["id"].map(recent).fillna(0.0)
    snapshot["ppg"] = (snapshot["total_points"] / snapshot["id"].map(appearances)).fillna(0.0)
    snapshot["ep_next"] = snapshot["form"]
    snapshot["status"] = "a"
    snapshot["chance_of_playing"] = None
    snapshot["news"] = ""
    snapshot["scout_risks"] = [[] for _ in range(len(snapshot))]
    return snapshot


def fixtures_as_of(fixtures: pd.DataFrame, gameweek: int) -> pd.DataFrame:
    snapshot = fixtures.copy()
    future = snapshot["gw"].isna() | (snapshot["gw"] >= gameweek)
    snapshot.loc[future, ["team_h_score", "team_a_score"]] = None
    snapshot.loc[future, "finished"] = False
    return snapshot


def legacy_projection(players: pd.DataFrame, fixtures: pd.DataFrame, gameweek: int) -> pd.Series:
    """The previous heuristic: form/PPG/ep_next blend scaled by FPL's 1-5 difficulty."""
    upcoming = fixtures[fixtures["gw"] == gameweek]
    difficulties: dict[int, list[int]] = {}
    for fixture in upcoming.itertuples():
        difficulties.setdefault(int(fixture.team_h_id), []).append(int(fixture.team_h_difficulty))
        difficulties.setdefault(int(fixture.team_a_id), []).append(int(fixture.team_a_difficulty))
    base = players["form"] * 0.55 + players["ppg"] * 0.30 + players["ep_next"] * 0.15
    fixture_factor = players["team_id"].map(
        lambda team_id: sum(LEGACY_DIFFICULTY_MULTIPLIERS.get(value, 1.0) for value in difficulties.get(int(team_id), []))
    )
    minute_share = (players["minutes"] / (max(1, gameweek - 1) * 90)).clip(upper=1.0)
    return pd.Series((base * fixture_factor * (0.65 + 0.35 * minute_share)).to_numpy(), index=players["id"])


def _metrics(predicted: pd.Series, actual: pd.Series, top_n: int) -> dict[str, float]:
    error = predicted - actual
    top_ids = predicted.sort_values(ascending=False).head(top_n).index
    return {
        "rmse": float(np.sqrt((error ** 2).mean())),
        "mae": float(error.abs().mean()),
        "spearman": float(predicted.rank().corr(actual.rank())),
        f"top{top_n}_points": float(actual.loc[top_ids].sum()),
    }


def run_backtest(
    bootstrap: Mapping,
    raw_fixtures: list[Mapping],
    live_payloads: Mapping[int, Mapping],
    target_gameweeks: list[int],
    config: ModelConfig = ModelConfig(),
    top_n: int = 20,
) -> pd.DataFrame:
    teams = frames.build_teams(bootstrap)
    players = frames.build_players(bootstrap)
    fixtures = frames.build_fixtures(raw_fixtures, teams)
    stats = frames.build_gameweek_stats(live_payloads)
    scoring = scoring_from_bootstrap(bootstrap)
    rows = []
    for gameweek in target_gameweeks:
        actual = stats[stats["gw"] == gameweek].groupby("player_id")["total_points"].sum()
        if actual.empty:
            continue
        snapshot = players_as_of(players, stats, gameweek)
        fixture_snapshot = fixtures_as_of(fixtures, gameweek)
        history = stats[stats["gw"] < gameweek]
        active = history[(history["gw"] >= gameweek - 3) & (history["minutes"] > 0)]["player_id"].unique()
        model = project_players(snapshot, teams, fixture_snapshot, history, [gameweek], scoring, config)
        predictions = {
            "new_model": model.players.set_index("id")[f"xp_gw{gameweek}"],
            "legacy": legacy_projection(snapshot, fixture_snapshot, gameweek),
        }
        evaluated = pd.Index(active).intersection(actual.index)
        for name, predicted in predictions.items():
            rows.append({
                "gameweek": gameweek,
                "model": name,
                "players": len(evaluated),
                **_metrics(predicted.reindex(evaluated).fillna(0.0), actual.reindex(evaluated).fillna(0.0), top_n),
            })
    return pd.DataFrame(rows)


def summarise_backtest(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return results
    return results.groupby("model").mean(numeric_only=True).drop(columns=["gameweek"]).round(3)
