from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from fpl_data import frames
from fpl_data.projections import (
    DEFAULT_SCORING,
    difficulty_rating,
    expected_floor_division,
    fit_team_ratings,
    fixture_availability,
    parse_return_date,
    poisson_at_least,
    project_players,
    scoring_from_bootstrap,
    upcoming_gameweeks,
)
from tests.synthetic import make_season, player_id


def load(upcoming: list[tuple[int, int, int]] | None = None):
    bootstrap, raw_fixtures, live = make_season(upcoming)
    teams = frames.build_teams(bootstrap)
    players = frames.build_players(bootstrap)
    fixtures = frames.build_fixtures(raw_fixtures, teams)
    stats = frames.build_gameweek_stats(live)
    gameweeks = frames.build_gameweeks(bootstrap)
    return bootstrap, teams, players, fixtures, stats, gameweeks


def fixtures_on(dates: list[str], gameweeks: list[int] | None = None) -> pd.DataFrame:
    return pd.DataFrame({
        "kickoff_time": pd.to_datetime(dates, utc=True),
        "gw": gameweeks or list(range(10, 10 + len(dates))),
    })


@pytest.mark.parametrize(
    ("news", "reference", "expected"),
    [
        ("Hamstring injury - Expected back 21 Nov", "2026-10-17", "2026-11-21"),
        ("Hamstring injury - Expected back 2 Jan", "2026-10-10", "2027-01-02"),
        ("Suspended until 29 Nov", "2026-10-27", "2026-11-29"),
        ("Thigh injury - Unknown return date", "2026-10-21", None),
        ("Knock - 75% chance of playing", "2026-10-21", None),
    ],
)
def test_parse_return_date(news: str, reference: str, expected: str | None) -> None:
    parsed = parse_return_date(news, pd.Timestamp(reference, tz="UTC"))

    assert parsed == (pd.Timestamp(expected, tz="UTC") if expected else None)


def test_fixture_availability_follows_status_news_and_loan_rules() -> None:
    fixtures = fixtures_on(["2026-11-01", "2026-11-08", "2026-11-22", "2026-11-29", "2026-12-06"], [10, 11, 12, 13, 14])
    reference = pd.Timestamp("2026-10-20", tz="UTC")

    assert fixture_availability({"status": "a"}, fixtures).tolist() == [1, 1, 1, 1, 1]
    assert fixture_availability({"status": "u"}, fixtures).tolist() == [0, 0, 0, 0, 0]
    assert fixture_availability({"status": "d", "chance_of_playing": 75}, fixtures).tolist() == pytest.approx([0.75, 0.875, 0.9375, 0.96875, 0.984375])
    returning = {"status": "i", "chance_of_playing": 0, "news": "Hamstring injury - Expected back 21 Nov", "news_added": reference}
    assert fixture_availability(returning, fixtures).tolist() == [0.0, 0.0, 0.8, 1.0, 1.0]
    suspended = {"status": "s", "news": "Suspended until 29 Nov", "news_added": reference}
    assert fixture_availability(suspended, fixtures).tolist() == [0.0, 0.0, 0.0, 1.0, 1.0]
    unknown = {"status": "i", "chance_of_playing": 0, "news": "Knee injury - Unknown return date"}
    assert fixture_availability(unknown, fixtures).tolist() == pytest.approx([0.0, 0.0, 0.0, 0.2, 0.4])
    loan = {"status": "a", "scout_risks": [{"property": "loan_ineligible", "gameweek": 12}]}
    assert fixture_availability(loan, fixtures).tolist() == [1.0, 1.0, 0.0, 1.0, 1.0]


def test_poisson_helpers_match_brute_force() -> None:
    lam = np.array([0.0, 1.3, 10.0])
    pmf = lambda value, k: math.exp(-value) * value**k / math.factorial(k)

    assert poisson_at_least(lam, np.array([10, 10, 10])) == pytest.approx([0.0] + [1 - sum(pmf(value, k) for k in range(10)) for value in lam[1:]])
    assert poisson_at_least(lam, np.array([0, 0, 0])).tolist() == [0.0, 0.0, 0.0]
    assert expected_floor_division(lam, 2) == pytest.approx([sum((k // 2) * pmf(value, k) for k in range(60)) for value in lam], abs=1e-6)


def test_difficulty_rating_maps_goal_difference_to_five_levels() -> None:
    assert difficulty_rating(np.array([1.0, 0.5, 0.0, -0.5, -1.0])).tolist() == [1, 2, 3, 4, 5]


def test_scoring_reads_current_rules_from_bootstrap() -> None:
    scoring = scoring_from_bootstrap({"game_config": {"scoring": {"goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}, "assists": 3, "saves": 1}}})

    assert scoring["goals_scored"]["GKP"] == 10
    assert scoring["clean_sheets"] == DEFAULT_SCORING["clean_sheets"]
    assert scoring_from_bootstrap(None) == DEFAULT_SCORING


def test_team_ratings_learn_attack_strength_and_home_advantage() -> None:
    _, teams, players, fixtures, stats, _ = load()

    ratings = fit_team_ratings(fixtures, teams)

    assert ratings.attack[1] == max(ratings.attack.values())
    assert ratings.home > 0
    home_goals, away_goals = ratings.expected_goals(1, 2)
    reverse_home, reverse_away = ratings.expected_goals(2, 1)
    assert home_goals > reverse_away
    assert away_goals < reverse_home


def test_upcoming_gameweeks_starts_at_next_deadline() -> None:
    *_, gameweeks = load()

    assert upcoming_gameweeks(gameweeks, 2) == [4, 5]
    assert upcoming_gameweeks(gameweeks, 10) == [4, 5, 6]


def test_projection_covers_every_player_and_gameweek() -> None:
    bootstrap, teams, players, fixtures, stats, _ = load()

    projections = project_players(players, teams, fixtures, stats, [4, 5, 6], scoring_from_bootstrap(bootstrap))

    assert len(projections.by_gameweek) == len(players) * 3
    assert (projections.by_gameweek["xp"] > 0).all()
    assert projections.xp_matrix().shape == (len(players), 3)
    summary = projections.players.set_index("id")
    assert summary.loc[player_id(1, 6), "xp_total"] > summary.loc[player_id(2, 6), "xp_total"]
    assert summary.loc[player_id(1, 6), "recent_points"] == [8, 8, 8]


def test_attacking_points_scale_with_fixture_expected_goals() -> None:
    bootstrap, teams, players, fixtures, stats, _ = load()

    rows = project_players(players, teams, fixtures, stats, [4, 5, 6], scoring_from_bootstrap(bootstrap)).by_fixture
    forward = rows[rows["player_id"] == player_id(2, 6)].sort_values("xg_for")

    assert forward["pts_goals"].is_monotonic_increasing
    assert forward["xg_for"].iloc[-1] > forward["xg_for"].iloc[0]


def test_double_gameweeks_add_up_and_blanks_score_zero() -> None:
    bootstrap, teams, players, fixtures, stats, _ = load([(4, 2, 1), (4, 1, 3), (5, 3, 1), (5, 4, 2)])

    projections = project_players(players, teams, fixtures, stats, [4, 5], scoring_from_bootstrap(bootstrap))
    xp = projections.xp_matrix()

    assert len(projections.by_fixture[(projections.by_fixture["player_id"] == player_id(1, 6)) & (projections.by_fixture["gw"] == 4)]) == 2
    assert xp.loc[player_id(4, 6), 4] == 0
    assert xp.loc[player_id(1, 6), 4] > 1.5 * xp.loc[player_id(1, 6), 5]


def test_injured_player_projects_zero_until_expected_return() -> None:
    bootstrap, teams, players, fixtures, stats, _ = load()
    injured = players["id"] == player_id(2, 6)
    players.loc[injured, "status"] = "i"
    players.loc[injured, "chance_of_playing"] = 0
    players.loc[injured, "news"] = "Hamstring injury - Expected back 25 Aug"
    players.loc[injured, "news_added"] = pd.Timestamp("2026-08-20", tz="UTC")

    projections = project_players(players, teams, fixtures, stats, [4, 5, 6], scoring_from_bootstrap(bootstrap))
    xp = projections.xp_matrix().loc[player_id(2, 6)]
    summary = projections.players.set_index("id").loc[player_id(2, 6)]

    assert xp[4] == 0
    assert 0 < xp[5] < xp[6]
    assert summary["availability_note"] == "Hamstring injury - Expected back 25 Aug"
    assert summary["return_date"] == pd.Timestamp("2026-08-25", tz="UTC")


def test_rotation_risk_reduces_expected_minutes_and_points() -> None:
    bootstrap, teams, players, fixtures, stats, _ = load()
    rotation = stats["player_id"] == player_id(2, 5)
    stats.loc[rotation, ["minutes", "starts"]] = [20, 0]

    summary = project_players(players, teams, fixtures, stats, [4, 5, 6], scoring_from_bootstrap(bootstrap)).players.set_index("id")

    assert summary.loc[player_id(2, 5), "xmins_next"] < 0.5 * summary.loc[player_id(2, 4), "xmins_next"]
    assert summary.loc[player_id(2, 5), "xp_total"] < summary.loc[player_id(2, 4), "xp_total"]
