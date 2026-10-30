from __future__ import annotations

from fpl_data import frames
from tests.synthetic import make_season


def test_build_players_maps_positions_prices_and_flags() -> None:
    bootstrap, _, _ = make_season()
    bootstrap["elements"][0].update({
        "status": "d",
        "chance_of_playing_next_round": 75,
        "news": "Knock - 75% chance of playing",
        "scout_risks": {"property": "suspension_risk", "gameweek": None},
    })

    players = frames.build_players(bootstrap).set_index("id")
    first = players.loc[11]

    assert first["position"] == "GKP"
    assert first["team_short"] == "T1"
    assert first["cost_m"] == 5.5
    assert first["status_label"] == "Doubtful"
    assert first["chance_of_playing"] == 75
    assert first["scout_risks"] == [{"property": "suspension_risk", "gameweek": None}]
    assert players.loc[16, "expected_goals"] == 0.9


def test_build_fixtures_adds_team_names_and_gameweek() -> None:
    bootstrap, raw_fixtures, _ = make_season()

    fixtures = frames.build_fixtures(raw_fixtures, frames.build_teams(bootstrap))

    assert fixtures.loc[0, ["team_h_short", "team_a_short", "gw"]].tolist() == ["T1", "T2", 1]
    assert fixtures["finished"].sum() == 6
    assert str(fixtures["kickoff_time"].dt.tz) == "UTC"


def test_build_gameweek_stats_flattens_live_payloads() -> None:
    _, _, live = make_season()

    stats = frames.build_gameweek_stats(live)

    assert len(stats) == 24 * 3
    row = stats[(stats["player_id"] == 16) & (stats["gw"] == 2)].iloc[0]
    assert row["expected_goals"] == 0.8
    assert row["total_points"] == 8
    assert frames.build_gameweek_stats({}).empty
