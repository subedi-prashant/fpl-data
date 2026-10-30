"""Expected-points (xP) projections for every FPL player and upcoming fixture.

The model follows the component approach used by public FPL models such as AIrsenal
and the open-source FPL solver ecosystem:

1. Team model: Poisson attack/defence ratings with home advantage, fitted on this
   season's results (a blend of xG and goals), time-decayed and regularised toward
   FPL's own team strength ratings so early-season estimates stay stable.
2. Availability per fixture from FPL status, chance of playing, injury/suspension
   return dates parsed from the news text and loan restrictions.
3. Minutes model from recent appearances: start probability, minutes when starting,
   substitute appearances and the 60-minute rate.
4. Per-90 event rates (xG, xA, saves, defensive actions, bonus, cards), weighted
   toward recent gameweeks and shrunk toward a price-based positional prior.
5. Official FPL scoring applied fixture by fixture, so blank and double gameweeks
   are handled naturally.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

POSITIONS = ("GKP", "DEF", "MID", "FWD")
DEFAULT_SCORING: dict = {
    "long_play": 2,
    "short_play": 1,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "saves": 1,
    "yellow_cards": -1,
    "red_cards": -3,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
}
DEFENSIVE_CONTRIBUTION_THRESHOLD = {"GKP": 0, "DEF": 10, "MID": 12, "FWD": 12}
SAVES_PER_POINT = 3
GOALS_CONCEDED_PER_POINT = 2
RATE_COLUMNS = {
    "xg90": "expected_goals",
    "xa90": "expected_assists",
    "saves90": "saves",
    "dc90": "defensive_contribution",
    "bonus90": "bonus",
    "yc90": "yellow_cards",
    "rc90": "red_cards",
}
FALLBACK_RATES = {
    "xg90": {"GKP": 0.0, "DEF": 0.06, "MID": 0.15, "FWD": 0.35},
    "xa90": {"GKP": 0.01, "DEF": 0.07, "MID": 0.15, "FWD": 0.12},
    "saves90": {"GKP": 2.8, "DEF": 0.0, "MID": 0.0, "FWD": 0.0},
    "dc90": {"GKP": 0.0, "DEF": 9.0, "MID": 9.0, "FWD": 5.0},
    "bonus90": {"GKP": 0.25, "DEF": 0.25, "MID": 0.25, "FWD": 0.3},
    "yc90": {"GKP": 0.03, "DEF": 0.15, "MID": 0.15, "FWD": 0.1},
    "rc90": {"GKP": 0.003, "DEF": 0.005, "MID": 0.005, "FWD": 0.004},
}
DIFFICULTY_LABELS = {1: "Very easy", 2: "Easy", 3: "Medium", 4: "Hard", 5: "Very hard"}
_MONTHS = {name: index for index, name in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_RETURN_DATE = re.compile(r"(?:expected back|suspended until|back on|return(?:s|ing)? on)\s+(\d{1,2})\s+([A-Za-z]{3,9})", re.IGNORECASE)


@dataclass(frozen=True)
class ModelConfig:
    form_half_life: float = 4.0
    minutes_half_life: float = 3.0
    prior_minutes: float = 450.0
    team_half_life: float = 12.0
    team_xg_weight: float = 0.7
    team_prior_matches: float = 6.0
    home_advantage_prior: float = 0.2
    strength_prior_scale: float = 3.0
    overall_strength_prior_scale: float = 0.4
    doubtful_recovery: float = 0.5


@dataclass(frozen=True)
class TeamRatings:
    intercept: float
    home: float
    attack: Mapping[int, float]
    defence: Mapping[int, float]

    def expected_goals(self, home_id: int, away_id: int) -> tuple[float, float]:
        home_goals = math.exp(self.intercept + self.home + self.attack.get(home_id, 0.0) - self.defence.get(away_id, 0.0))
        away_goals = math.exp(self.intercept + self.attack.get(away_id, 0.0) - self.defence.get(home_id, 0.0))
        return home_goals, away_goals

    def baseline_for(self, team_id: int) -> float:
        return math.exp(self.intercept + self.home / 2 + self.attack.get(team_id, 0.0))

    def baseline_against(self, team_id: int) -> float:
        return math.exp(self.intercept + self.home / 2 - self.defence.get(team_id, 0.0))


@dataclass
class Projections:
    gameweeks: list[int]
    by_fixture: pd.DataFrame
    by_gameweek: pd.DataFrame
    players: pd.DataFrame
    team_fixtures: pd.DataFrame
    ratings: TeamRatings
    config: ModelConfig = field(default_factory=ModelConfig)

    def xp_matrix(self) -> pd.DataFrame:
        matrix = self.by_gameweek.pivot_table(index="player_id", columns="gw", values="xp", aggfunc="sum")
        return matrix.reindex(index=self.players["id"], columns=self.gameweeks, fill_value=0.0).fillna(0.0)


def scoring_from_bootstrap(bootstrap: Mapping | None) -> dict:
    scoring = {key: (dict(value) if isinstance(value, Mapping) else value) for key, value in DEFAULT_SCORING.items()}
    raw = ((bootstrap or {}).get("game_config") or {}).get("scoring") or {}
    for key, default in DEFAULT_SCORING.items():
        if key not in raw:
            continue
        if isinstance(default, Mapping) and isinstance(raw[key], Mapping):
            scoring[key] = {position: raw[key].get(position, default[position]) for position in POSITIONS}
        elif not isinstance(default, Mapping) and not isinstance(raw[key], Mapping):
            scoring[key] = raw[key]
    return scoring


def upcoming_gameweeks(gameweeks: pd.DataFrame, horizon: int) -> list[int]:
    upcoming = gameweeks[gameweeks["is_next"] == True]
    if upcoming.empty:
        upcoming = gameweeks[gameweeks["finished"] == False].sort_values("id").head(1)
    if upcoming.empty:
        return []
    first = int(upcoming.iloc[0]["id"])
    last = int(gameweeks["id"].max())
    return list(range(first, min(last, first + horizon - 1) + 1))


def _decay(age: pd.Series | np.ndarray, half_life: float) -> np.ndarray:
    return np.power(0.5, np.asarray(age, dtype=float) / max(half_life, 1e-6))


def _poisson_pmf(lam: np.ndarray, max_k: int) -> np.ndarray:
    lam = np.clip(np.asarray(lam, dtype=float), 0.0, None)[:, None]
    k = np.arange(max_k + 1)[None, :]
    log_pmf = k * np.log(np.where(lam > 0, lam, 1.0)) - lam - np.array([math.lgamma(value + 1) for value in range(max_k + 1)])[None, :]
    pmf = np.exp(log_pmf)
    pmf[:, 1:] = np.where(lam > 0, pmf[:, 1:], 0.0)
    pmf[:, 0] = np.exp(-lam[:, 0])
    return pmf


def poisson_at_least(lam: np.ndarray, threshold: np.ndarray) -> np.ndarray:
    lam = np.asarray(lam, dtype=float)
    threshold = np.asarray(threshold, dtype=int)
    max_k = int(threshold.max()) if threshold.size else 0
    if max_k <= 0:
        return np.zeros_like(lam)
    pmf = _poisson_pmf(lam, max_k)
    below = np.where(np.arange(max_k + 1)[None, :] < threshold[:, None], pmf, 0.0).sum(axis=1)
    return np.where(threshold > 0, np.clip(1.0 - below, 0.0, 1.0), 0.0)


def expected_floor_division(lam: np.ndarray, divisor: int) -> np.ndarray:
    lam = np.asarray(lam, dtype=float)
    peak = float(lam.max()) if lam.size else 0.0
    max_k = int(max(25, math.ceil(peak + 10 * math.sqrt(peak) + 10)))
    pmf = _poisson_pmf(lam, max_k)
    return (pmf * (np.arange(max_k + 1) // divisor)[None, :]).sum(axis=1)


def parse_return_date(news: str, reference: pd.Timestamp | None) -> pd.Timestamp | None:
    match = _RETURN_DATE.search(news or "")
    if not match:
        return None
    month = _MONTHS.get(match.group(2)[:3].lower())
    if month is None:
        return None
    reference = reference if reference is not None and not pd.isna(reference) else pd.Timestamp.now(tz="UTC")
    try:
        candidate = pd.Timestamp(year=reference.year, month=month, day=int(match.group(1)), tz="UTC")
    except ValueError:
        return None
    if candidate < reference.normalize() - pd.Timedelta(days=45):
        candidate = candidate.replace(year=candidate.year + 1)
    return candidate


def _loan_ineligible_gameweeks(scout_risks: object) -> set[int]:
    if not isinstance(scout_risks, list):
        return set()
    return {
        int(risk["gameweek"])
        for risk in scout_risks
        if isinstance(risk, Mapping) and risk.get("property") == "loan_ineligible" and risk.get("gameweek") is not None
    }


def fixture_availability(player: Mapping, fixtures: pd.DataFrame, config: ModelConfig = ModelConfig()) -> np.ndarray:
    """Probability the player is available for each fixture (rows ordered by kickoff)."""
    count = len(fixtures)
    if count == 0:
        return np.zeros(0)
    status = str(player.get("status") or "a")
    if status in {"u", "n"}:
        return np.zeros(count)
    chance = pd.to_numeric(player.get("chance_of_playing"), errors="coerce")
    news = str(player.get("news") or "")
    return_date = parse_return_date(news, player.get("news_added"))
    kickoffs = pd.to_datetime(fixtures["kickoff_time"], utc=True, errors="coerce")
    ordinal = np.arange(count, dtype=float)
    if status == "a":
        availability = np.ones(count)
    elif return_date is not None and status in {"i", "s", "d"}:
        back = (kickoffs.dt.normalize() >= return_date).fillna(False).to_numpy()
        first_back = np.argmax(back) if back.any() else count
        availability = np.where(back, 1.0, 0.0)
        if status != "s" and first_back < count:
            availability[first_back] = 0.8
    elif status == "s":
        availability = np.where(ordinal >= 1, 1.0, 0.0)
    elif status == "d" or (pd.notna(chance) and chance > 0):
        first = float(chance) / 100.0 if pd.notna(chance) else 0.5
        availability = 1.0 - (1.0 - first) * np.power(config.doubtful_recovery, ordinal)
    else:
        availability = np.clip(0.2 * (ordinal - 2.0), 0.0, 0.6)
    ineligible = _loan_ineligible_gameweeks(player.get("scout_risks"))
    if ineligible and "gw" in fixtures:
        availability = np.where(fixtures["gw"].astype(int).isin(ineligible).to_numpy(), 0.0, availability)
    return np.clip(availability, 0.0, 1.0)


def availability_note(player: Mapping) -> str:
    status = str(player.get("status") or "a")
    if status == "a":
        return ""
    news = str(player.get("news") or "").strip()
    return news or {"d": "Doubtful", "i": "Injured", "s": "Suspended", "u": "Unavailable", "n": "Not eligible"}.get(status, status)


def team_fixture_counts(fixtures: pd.DataFrame) -> pd.DataFrame:
    scheduled = fixtures.dropna(subset=["gw"])
    home = scheduled[["gw", "team_h_id"]].rename(columns={"team_h_id": "team_id"})
    away = scheduled[["gw", "team_a_id"]].rename(columns={"team_a_id": "team_id"})
    counts = pd.concat([home, away]).groupby(["team_id", "gw"]).size().rename("n_fixtures").reset_index()
    counts["gw"] = counts["gw"].astype(int)
    return counts


def team_fixture_xg(gameweek_stats: pd.DataFrame, players: pd.DataFrame, fixtures: pd.DataFrame) -> dict[tuple[int, int], float]:
    if gameweek_stats.empty or players.empty:
        return {}
    team_of = players.set_index("id")["team_id"]
    stats = gameweek_stats.assign(team_id=gameweek_stats["player_id"].map(team_of)).dropna(subset=["team_id"])
    team_xg = stats.groupby([stats["team_id"].astype(int), "gw"])["expected_goals"].sum()
    counts = team_fixture_counts(fixtures).set_index(["team_id", "gw"])["n_fixtures"]
    result = {}
    for fixture in fixtures[fixtures["finished"] == True].dropna(subset=["gw"]).itertuples():
        for team_id in (int(fixture.team_h_id), int(fixture.team_a_id)):
            key = (team_id, int(fixture.gw))
            if key in team_xg.index:
                result[(int(fixture.id), team_id)] = float(team_xg[key]) / max(1, int(counts.get(key, 1)))
    return result


def _strength_prior(teams: pd.DataFrame, config: ModelConfig) -> tuple[dict[int, float], dict[int, float]]:
    """Prior log-ratings from FPL's team strengths.

    FPL publishes separate attack/defence strengths in some seasons and only a 1-5
    overall strength in others, so fall back to the overall rating for both.
    """
    if teams.empty:
        return {}, {}
    team_ids = teams["id"].astype(int)

    def centred_log(prefix: str, scale: float) -> pd.Series | None:
        columns = [f"{prefix}_home", f"{prefix}_away"]
        if not all(column in teams for column in columns):
            return None
        values = teams[columns].astype(float).mean(axis=1)
        if (values <= 0).any():
            return None
        logged = np.log(values)
        return scale * (logged - logged.mean())

    attack = centred_log("strength_attack", config.strength_prior_scale)
    defence = centred_log("strength_defence", config.strength_prior_scale)
    if attack is None or defence is None:
        overall = centred_log("strength_overall", config.overall_strength_prior_scale)
        attack = defence = overall if overall is not None else pd.Series(0.0, index=teams.index)
    return dict(zip(team_ids, attack)), dict(zip(team_ids, defence))


def fit_team_ratings(
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    fixture_xg: Mapping[tuple[int, int], float] | None = None,
    config: ModelConfig = ModelConfig(),
) -> TeamRatings:
    team_ids = sorted(int(team_id) for team_id in teams["id"]) if not teams.empty else []
    index = {team_id: position for position, team_id in enumerate(team_ids)}
    count = len(team_ids)
    attack_prior, defence_prior = _strength_prior(teams, config)
    beta_prior = np.concatenate([
        [0.0, config.home_advantage_prior],
        [attack_prior.get(team_id, 0.0) for team_id in team_ids],
        [defence_prior.get(team_id, 0.0) for team_id in team_ids],
    ])
    finished = fixtures[(fixtures["finished"] == True) & fixtures["team_h_score"].notna() & fixtures["team_a_score"].notna()].dropna(subset=["gw"])
    fixture_xg = fixture_xg or {}
    rows, targets, weights = [], [], []
    latest = int(finished["gw"].max()) if not finished.empty else 0
    for fixture in finished.itertuples():
        weight = float(_decay(latest - int(fixture.gw), config.team_half_life))
        for attacking, defending, goals, is_home in (
            (int(fixture.team_h_id), int(fixture.team_a_id), float(fixture.team_h_score), 1.0),
            (int(fixture.team_a_id), int(fixture.team_h_id), float(fixture.team_a_score), 0.0),
        ):
            if attacking not in index or defending not in index:
                continue
            xg = fixture_xg.get((int(fixture.id), attacking))
            target = goals if xg is None else config.team_xg_weight * xg + (1 - config.team_xg_weight) * goals
            row = np.zeros(2 + 2 * count)
            row[0] = 1.0
            row[1] = is_home
            row[2 + index[attacking]] = 1.0
            row[2 + count + index[defending]] = -1.0
            rows.append(row)
            targets.append(target)
            weights.append(weight)
    mean_goals = float(np.average(targets, weights=weights)) if targets else 1.35
    precision = config.team_prior_matches * mean_goals
    penalty = np.diag(np.concatenate([[0.0, 40.0 * mean_goals], np.full(2 * count, precision)]))
    beta = beta_prior.copy()
    beta[0] = math.log(max(mean_goals, 0.1)) - config.home_advantage_prior / 2
    if rows:
        design = np.vstack(rows)
        y = np.asarray(targets)
        w = np.asarray(weights)
        for _ in range(50):
            mu = np.exp(design @ beta)
            gradient = design.T @ (w * (y - mu)) - penalty @ (beta - beta_prior)
            hessian = design.T @ (design * (w * mu)[:, None]) + penalty
            step = np.linalg.solve(hessian, gradient)
            beta += step
            if np.max(np.abs(step)) < 1e-9:
                break
    attack = beta[2:2 + count]
    defence = beta[2 + count:]
    intercept = beta[0] + attack.mean() - defence.mean()
    return TeamRatings(
        intercept=float(intercept),
        home=float(beta[1]),
        attack={team_id: float(attack[index[team_id]] - attack.mean()) for team_id in team_ids},
        defence={team_id: float(defence[index[team_id]] - defence.mean()) for team_id in team_ids},
    )


def difficulty_rating(goal_difference: np.ndarray | float) -> np.ndarray:
    """Map expected goal difference (for minus against) to a 1 (easy) to 5 (hard) scale."""
    edges = np.array([0.7, 0.25, -0.25, -0.7])
    return 1 + (np.asarray(goal_difference, dtype=float)[..., None] < edges).sum(axis=-1)


def build_team_fixtures(fixtures: pd.DataFrame, teams: pd.DataFrame, ratings: TeamRatings, gameweeks: list[int]) -> pd.DataFrame:
    columns = ["team_id", "fixture_id", "gw", "kickoff_time", "opponent_id", "opponent_short", "is_home", "xg_for", "xg_against", "cs_prob", "difficulty", "label"]
    upcoming = fixtures[fixtures["gw"].isin(gameweeks)] if gameweeks else fixtures.iloc[0:0]
    if upcoming.empty:
        return pd.DataFrame(columns=columns)
    short_names = teams.set_index("id")["short_name"].to_dict() if not teams.empty else {}
    rows = []
    for fixture in upcoming.itertuples():
        home_id, away_id = int(fixture.team_h_id), int(fixture.team_a_id)
        home_goals, away_goals = ratings.expected_goals(home_id, away_id)
        for team_id, opponent_id, is_home, goals_for, goals_against in (
            (home_id, away_id, True, home_goals, away_goals),
            (away_id, home_id, False, away_goals, home_goals),
        ):
            opponent_short = short_names.get(opponent_id, str(opponent_id))
            rows.append({
                "team_id": team_id,
                "fixture_id": int(fixture.id),
                "gw": int(fixture.gw),
                "kickoff_time": fixture.kickoff_time,
                "opponent_id": opponent_id,
                "opponent_short": opponent_short,
                "is_home": is_home,
                "xg_for": goals_for,
                "xg_against": goals_against,
                "cs_prob": math.exp(-goals_against),
                "label": f"{opponent_short} ({'H' if is_home else 'A'})",
            })
    team_fixtures = pd.DataFrame(rows)
    team_fixtures["difficulty"] = difficulty_rating((team_fixtures["xg_for"] - team_fixtures["xg_against"]).to_numpy()).astype(int)
    return team_fixtures.sort_values(["team_id", "kickoff_time", "fixture_id"]).reset_index(drop=True)[columns]


def _price_prior(players: pd.DataFrame, stat: str, rate_name: str, min_minutes: float = 270.0) -> pd.Series:
    prior = pd.Series(0.0, index=players.index)
    for position in POSITIONS:
        mask = players["position"] == position
        fallback = FALLBACK_RATES[rate_name][position]
        sample = players[mask & (players["minutes"] >= min_minutes)]
        if len(sample) < 8 or stat not in sample:
            prior[mask] = fallback
            continue
        rates = sample[stat] / (sample["minutes"] / 90.0)
        costs = sample["now_cost"].astype(float)
        weights = sample["minutes"].astype(float)
        if costs.nunique() > 1:
            slope, intercept = np.polyfit(costs, rates, 1, w=np.sqrt(weights))
        else:
            slope, intercept = 0.0, float(np.average(rates, weights=weights))
        mean_rate = float(np.average(rates, weights=weights))
        estimate = intercept + slope * players.loc[mask, "now_cost"].astype(float)
        prior[mask] = estimate.clip(lower=0.25 * mean_rate, upper=3.0 * max(mean_rate, 1e-6))
    return prior


def _player_rates(players: pd.DataFrame, gameweek_stats: pd.DataFrame, config: ModelConfig) -> pd.DataFrame:
    rates = pd.DataFrame(index=players["id"])
    if gameweek_stats.empty:
        weighted = pd.DataFrame(0.0, index=players["id"], columns=["minutes", *RATE_COLUMNS.values()])
    else:
        latest = int(gameweek_stats["gw"].max())
        stats = gameweek_stats.assign(weight=_decay(latest - gameweek_stats["gw"], config.form_half_life))
        value_columns = ["minutes", *RATE_COLUMNS.values()]
        weighted = stats[value_columns].mul(stats["weight"], axis=0).groupby(stats["player_id"]).sum()
        weighted = weighted.reindex(players["id"], fill_value=0.0)
    indexed = players.set_index("id")
    pseudo = config.prior_minutes / 90.0
    for rate_name, stat in RATE_COLUMNS.items():
        prior = _price_prior(players, stat, rate_name).to_numpy()
        rates[rate_name] = (weighted[stat].to_numpy() + prior * pseudo) / (weighted["minutes"].to_numpy() / 90.0 + pseudo)
    rates["weighted_minutes"] = weighted["minutes"].to_numpy()
    rates["position"] = indexed["position"]
    return rates


def _minutes_model(players: pd.DataFrame, gameweek_stats: pd.DataFrame, fixtures: pd.DataFrame, config: ModelConfig) -> pd.DataFrame:
    model = pd.DataFrame(index=players["id"])
    start_prior = _start_share_prior(players, fixtures)
    if gameweek_stats.empty:
        model["p_start"] = start_prior.to_numpy()
        model["p_sub"] = 0.1
        model["mins_start"] = 80.0
        model["mins_sub"] = 20.0
        model["p60_start"] = 0.85
        return model
    counts = team_fixture_counts(fixtures)
    team_of = players.set_index("id")["team_id"]
    stats = gameweek_stats.assign(team_id=gameweek_stats["player_id"].map(team_of)).dropna(subset=["team_id"])
    stats["team_id"] = stats["team_id"].astype(int)
    stats = stats.merge(counts, on=["team_id", "gw"], how="left")
    stats = stats[stats["n_fixtures"].fillna(0) > 0].copy()
    latest = int(gameweek_stats["gw"].max())
    stats["w"] = _decay(latest - stats["gw"], config.minutes_half_life)
    stats["per_fixture_minutes"] = (stats["minutes"] / stats["n_fixtures"]).clip(upper=90.0)
    stats["start_share"] = (stats["starts"] / stats["n_fixtures"]).clip(upper=1.0)
    stats["sub_share"] = ((stats["minutes"] > 0) & (stats["starts"] < stats["n_fixtures"])).astype(float) * (1.0 - stats["start_share"])
    stats["sixty"] = (stats["per_fixture_minutes"] >= 60).astype(float)
    grouped = stats.assign(
        w_start=stats["w"] * stats["start_share"],
        w_sub=stats["w"] * stats["sub_share"],
        w_start_minutes=stats["w"] * stats["start_share"] * stats["per_fixture_minutes"],
        w_sub_minutes=stats["w"] * stats["sub_share"] * stats["per_fixture_minutes"].clip(upper=45.0),
        w_start_sixty=stats["w"] * stats["start_share"] * stats["sixty"],
    ).groupby("player_id")[["w", "w_start", "w_sub", "w_start_minutes", "w_sub_minutes", "w_start_sixty"]].sum()
    grouped = grouped.reindex(players["id"], fill_value=0.0)
    prior_strength = 1.0
    model["p_start"] = (grouped["w_start"] + prior_strength * start_prior.to_numpy()) / (grouped["w"] + prior_strength)
    model["p_sub"] = (grouped["w_sub"] + prior_strength * 0.1) / (grouped["w"] + prior_strength)
    model["p_sub"] = np.minimum(model["p_sub"], 1.0 - model["p_start"])
    model["mins_start"] = (grouped["w_start_minutes"] + 80.0) / (grouped["w_start"] + 1.0)
    model["mins_sub"] = (grouped["w_sub_minutes"] + 20.0) / (grouped["w_sub"] + 1.0)
    model["p60_start"] = (grouped["w_start_sixty"] + 0.85) / (grouped["w_start"] + 1.0)
    return model


def _start_share_prior(players: pd.DataFrame, fixtures: pd.DataFrame) -> pd.Series:
    played = fixtures[fixtures["finished"] == True]
    team_games = pd.concat([played["team_h_id"], played["team_a_id"]]).value_counts() if not played.empty else pd.Series(dtype=float)
    games = players["team_id"].map(team_games).fillna(0).astype(float)
    share = (players["starts"] / games.where(games > 0)).clip(0, 1)
    prior = pd.Series(0.3, index=players.index)
    for position in POSITIONS:
        mask = (players["position"] == position) & share.notna() & (games > 0)
        if mask.sum() >= 8 and players.loc[mask, "now_cost"].nunique() > 1:
            slope, intercept = np.polyfit(players.loc[mask, "now_cost"].astype(float), share[mask], 1)
            prior[players["position"] == position] = (intercept + slope * players.loc[players["position"] == position, "now_cost"]).clip(0.05, 0.75)
    return prior


def _form_summary(players: pd.DataFrame, gameweek_stats: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    summary = pd.DataFrame(index=players["id"])
    if gameweek_stats.empty:
        summary["recent_points"] = [[] for _ in range(len(players))]
        summary["xgi90_recent"] = 0.0
        summary["minutes_recent"] = 0.0
        return summary
    latest = int(gameweek_stats["gw"].max())
    recent = gameweek_stats[gameweek_stats["gw"] > latest - window]
    points = recent.pivot_table(index="player_id", columns="gw", values="total_points", aggfunc="sum").reindex(columns=range(max(1, latest - window + 1), latest + 1)).fillna(0.0)
    points = points.reindex(players["id"]).fillna(0.0)
    summary["recent_points"] = [list(map(int, row)) for row in points.to_numpy()]
    last_four = gameweek_stats[gameweek_stats["gw"] > latest - 4].groupby("player_id")[["expected_goals", "expected_assists", "minutes"]].sum().reindex(players["id"]).fillna(0.0)
    nineties = last_four["minutes"] / 90.0
    summary["xgi90_recent"] = ((last_four["expected_goals"] + last_four["expected_assists"]) / nineties.where(nineties >= 1)).fillna(0.0).to_numpy()
    summary["minutes_recent"] = (last_four["minutes"] / 4.0).to_numpy()
    return summary


def project_players(
    players: pd.DataFrame,
    teams: pd.DataFrame,
    fixtures: pd.DataFrame,
    gameweek_stats: pd.DataFrame,
    gameweeks: list[int],
    scoring: Mapping | None = None,
    config: ModelConfig = ModelConfig(),
) -> Projections:
    scoring = scoring or DEFAULT_SCORING
    ratings = fit_team_ratings(fixtures, teams, team_fixture_xg(gameweek_stats, players, fixtures), config)
    team_fixtures = build_team_fixtures(fixtures, teams, ratings, gameweeks)
    rates = _player_rates(players, gameweek_stats, config)
    minutes = _minutes_model(players, gameweek_stats, fixtures, config)
    model = players.set_index("id").join(rates.drop(columns=["position"])).join(minutes)

    rows = team_fixtures.merge(players[["id", "team_id"]].rename(columns={"id": "player_id"}), on="team_id", how="inner")
    rows = rows.sort_values(["player_id", "kickoff_time", "fixture_id"]).reset_index(drop=True)
    availability = np.zeros(len(rows))
    for player_id, group in rows.groupby("player_id", sort=False):
        availability[group.index.to_numpy()] = fixture_availability(model.loc[player_id].to_dict(), group, config)
    rows["availability"] = availability
    rows = rows.join(model[["position", "p_start", "p_sub", "mins_start", "mins_sub", "p60_start", *RATE_COLUMNS]], on="player_id")
    rows["base_for"] = rows["team_id"].map(ratings.baseline_for)
    rows["base_against"] = rows["team_id"].map(ratings.baseline_against)

    position = rows["position"]
    p_start = rows["availability"] * rows["p_start"]
    p_sub = rows["availability"] * rows["p_sub"]
    p_play = (p_start + p_sub).clip(upper=1.0)
    p60 = p_start * rows["p60_start"]
    xmins = p_start * rows["mins_start"] + p_sub * rows["mins_sub"]
    attack_multiplier = rows["xg_for"] / rows["base_for"]
    defence_multiplier = rows["xg_against"] / rows["base_against"]
    start_share_of_match = rows["mins_start"] / 90.0
    goal_points = position.map(scoring["goals_scored"]).astype(float)
    clean_sheet_points = position.map(scoring["clean_sheets"]).astype(float)
    conceded_points = position.map(scoring["goals_conceded"]).astype(float)
    dc_points = position.map(scoring["defensive_contribution"]).astype(float)
    thresholds = position.map(DEFENSIVE_CONTRIBUTION_THRESHOLD).astype(int).to_numpy()
    bonus_multiplier = np.where(
        position.isin(["MID", "FWD"]),
        np.sqrt(attack_multiplier),
        np.sqrt(np.exp(-rows["xg_against"]) / np.exp(-rows["base_against"])),
    )

    rows["xmins"] = xmins
    rows["p_play"] = p_play
    rows["pts_appearance"] = scoring["long_play"] * p60 + scoring["short_play"] * (p_play - p60)
    rows["pts_goals"] = rows["xg90"] * xmins / 90.0 * attack_multiplier * goal_points
    rows["pts_assists"] = rows["xa90"] * xmins / 90.0 * attack_multiplier * scoring["assists"]
    rows["pts_clean_sheet"] = p60 * np.exp(-rows["xg_against"] * start_share_of_match) * clean_sheet_points
    rows["pts_conceded"] = p_start * expected_floor_division((rows["xg_against"] * start_share_of_match).to_numpy(), GOALS_CONCEDED_PER_POINT) * conceded_points
    rows["pts_saves"] = np.where(
        position == "GKP",
        p_start * expected_floor_division((rows["saves90"] * start_share_of_match * defence_multiplier).to_numpy(), SAVES_PER_POINT) * scoring["saves"],
        0.0,
    )
    rows["pts_defensive"] = p_start * poisson_at_least((rows["dc90"] * start_share_of_match).to_numpy(), thresholds) * dc_points
    rows["pts_bonus"] = rows["bonus90"] * xmins / 90.0 * bonus_multiplier
    rows["pts_cards"] = (rows["yc90"] * scoring["yellow_cards"] + rows["rc90"] * scoring["red_cards"]) * xmins / 90.0
    component_columns = [column for column in rows.columns if column.startswith("pts_")]
    rows["xp"] = rows[component_columns].sum(axis=1)

    by_gameweek = rows.groupby(["player_id", "gw"]).agg(
        xp=("xp", "sum"),
        xmins=("xmins", "sum"),
        availability=("availability", "min"),
        fixtures=("label", lambda labels: " + ".join(labels)),
        difficulty=("difficulty", "max"),
        **{column: (column, "sum") for column in component_columns},
    ).reset_index()

    summary = players.copy()
    xp_wide = by_gameweek.pivot_table(index="player_id", columns="gw", values="xp", aggfunc="sum").reindex(columns=gameweeks).fillna(0.0)
    summary = summary.join(xp_wide.add_prefix("xp_gw").reindex(summary["id"]).reset_index(drop=True))
    for gameweek in gameweeks:
        summary[f"xp_gw{gameweek}"] = summary[f"xp_gw{gameweek}"].fillna(0.0)
    summary["xp_next"] = summary[f"xp_gw{gameweeks[0]}"] if gameweeks else 0.0
    summary["xp_total"] = summary[[f"xp_gw{gameweek}" for gameweek in gameweeks]].sum(axis=1) if gameweeks else 0.0
    summary["xp_per_gw"] = [list(np.round(row, 2)) for row in xp_wide.reindex(summary["id"]).fillna(0.0).to_numpy()] if gameweeks else [[] for _ in range(len(summary))]
    next_rows = by_gameweek[by_gameweek["gw"] == gameweeks[0]].set_index("player_id") if gameweeks else pd.DataFrame()
    summary["xmins_next"] = summary["id"].map(next_rows["xmins"]).fillna(0.0) if gameweeks else 0.0
    summary["availability_next"] = summary["id"].map(next_rows["availability"]).fillna(0.0) if gameweeks else 0.0
    summary["availability_note"] = [availability_note(player) for player in summary.to_dict("records")]
    summary["return_date"] = [parse_return_date(str(player.get("news") or ""), player.get("news_added")) if player.get("status") != "a" else None for player in summary.to_dict("records")]
    summary = summary.join(rates[["xg90", "xa90"]].reset_index(drop=True))
    summary["xgi90_model"] = summary["xg90"] + summary["xa90"]
    summary["p_start"] = minutes["p_start"].to_numpy()
    summary = summary.join(_form_summary(players, gameweek_stats).reset_index(drop=True))
    return Projections(
        gameweeks=list(gameweeks),
        by_fixture=rows,
        by_gameweek=by_gameweek,
        players=summary,
        team_fixtures=team_fixtures,
        ratings=ratings,
        config=config,
    )
