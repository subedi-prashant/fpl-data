from __future__ import annotations

import pandas as pd

from fpl_data.recommendations import (
    calculate_player_projections,
    calculate_selling_price,
    infer_purchase_prices,
    recommend_transfers,
    validate_replacement,
    validate_squad,
)


def make_players() -> pd.DataFrame:
    positions = ["GKP", "GKP", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    rows = []
    for player_id, position in enumerate(positions, start=1):
        team_id = {3: 1, 8: 1, 13: 1}.get(player_id, player_id + 1)
        rows.append({
            "id": player_id,
            "web_name": f"Player {player_id}",
            "team_id": team_id,
            "team": f"Team {team_id}",
            "team_short": f"T{team_id}",
            "position": position,
            "now_cost": 50,
            "purchase_cost": 50,
            "selling_price": 50,
            "form": 3.0,
            "ppg": 3.0,
            "ep_next": 3.0,
            "minutes": 360,
            "status": "a",
            "chance_of_playing": 100,
            "squad_pos": player_id,
        })
    return pd.DataFrame(rows)


def make_fixtures() -> pd.DataFrame:
    rows = []
    for gameweek in range(5, 8):
        for team_id in range(1, 20, 2):
            rows.append({
                "event": gameweek,
                "team_h": team_id,
                "team_a": team_id + 1,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
            })
    return pd.DataFrame(rows)


def test_calculate_selling_price_uses_fpl_profit_rule() -> None:
    assert calculate_selling_price(55, 50) == 52
    assert calculate_selling_price(56, 50) == 53
    assert calculate_selling_price(49, 50) == 49
    assert calculate_selling_price(50, 50) == 50


def test_infer_purchase_prices_uses_latest_permanent_transfer() -> None:
    players = pd.DataFrame([
        {"id": 1, "now_cost": 55, "cost_change_start": 5},
        {"id": 2, "now_cost": 60, "cost_change_start": 10},
    ])
    transfers = [
        {"element_in": 1, "element_in_cost": 51, "event": 2, "time": "2026-08-20T10:00:00Z"},
        {"element_in": 1, "element_in_cost": 53, "event": 4, "time": "2026-09-10T10:00:00Z"},
        {"element_in": 2, "element_in_cost": 55, "event": 5, "time": "2026-09-17T10:00:00Z"},
    ]

    result = infer_purchase_prices({1, 2}, players, transfers, ignored_events={5})

    assert result == {1: 53, 2: 50}


def test_validate_squad_checks_official_shape_and_club_limit() -> None:
    squad = make_players()

    checks = validate_squad(squad)

    assert checks["fifteen_players"]
    assert checks["position_quota"]
    assert checks["club_limit"]


def test_recommendations_use_sale_price_plus_bank_in_tenths() -> None:
    squad = make_players()
    squad.loc[squad["id"] == 3, ["now_cost", "purchase_cost", "selling_price", "form", "ppg", "ep_next"]] = [55, 50, 52, 1.0, 1.0, 1.0]
    candidates = pd.DataFrame([
        {
            "id": 100,
            "web_name": "Affordable",
            "team_id": 4,
            "team": "Team 4",
            "team_short": "T4",
            "position": "DEF",
            "now_cost": 55,
            "form": 8.0,
            "ppg": 8.0,
            "ep_next": 8.0,
            "minutes": 360,
            "status": "a",
            "chance_of_playing": 100,
        },
        {
            "id": 101,
            "web_name": "Too expensive",
            "team_id": 5,
            "team": "Team 5",
            "team_short": "T5",
            "position": "DEF",
            "now_cost": 56,
            "form": 9.0,
            "ppg": 9.0,
            "ep_next": 9.0,
            "minutes": 360,
            "status": "a",
            "chance_of_playing": 100,
        },
    ])
    players = pd.concat([squad.drop(columns=["purchase_cost", "selling_price", "squad_pos"]), candidates], ignore_index=True)

    recommendations = recommend_transfers(squad, players, make_fixtures(), bank=3, next_gameweek=5, horizon=3)
    outgoing = recommendations[recommendations["player_out_id"] == 3]

    assert 100 in outgoing["player_in_id"].tolist()
    assert 101 not in outgoing["player_in_id"].tolist()
    move = outgoing[outgoing["player_in_id"] == 100].iloc[0]
    assert move["available_budget"] == 55
    assert move["bank_after"] == 0


def test_recommendations_preserve_position_and_three_player_club_limit() -> None:
    squad = make_players()
    squad.loc[squad["id"].isin([3, 4]), ["form", "ppg", "ep_next"]] = [1.0, 1.0, 1.0]
    candidates = pd.DataFrame([
        {
            "id": 100,
            "web_name": "Fourth club player",
            "team_id": 1,
            "team": "Team 1",
            "team_short": "T1",
            "position": "DEF",
            "now_cost": 50,
            "form": 8.0,
            "ppg": 8.0,
            "ep_next": 8.0,
            "minutes": 360,
            "status": "a",
            "chance_of_playing": 100,
        },
        {
            "id": 101,
            "web_name": "Wrong position",
            "team_id": 4,
            "team": "Team 4",
            "team_short": "T4",
            "position": "MID",
            "now_cost": 50,
            "form": 9.0,
            "ppg": 9.0,
            "ep_next": 9.0,
            "minutes": 360,
            "status": "a",
            "chance_of_playing": 100,
        },
    ])
    players = pd.concat([squad.drop(columns=["purchase_cost", "selling_price", "squad_pos"]), candidates], ignore_index=True)

    recommendations = recommend_transfers(squad, players, make_fixtures(), bank=0, next_gameweek=5, horizon=3)

    assert recommendations[(recommendations["player_out_id"] == 4) & (recommendations["player_in_id"] == 100)].empty
    assert not recommendations[(recommendations["player_out_id"] == 3) & (recommendations["player_in_id"] == 100)].empty
    assert recommendations[recommendations["player_out_id"] == 3]["player_in_id"].tolist() == [100]


def test_validate_replacement_reports_every_transfer_rule() -> None:
    squad = make_players()
    incoming = {
        "id": 100,
        "team_id": 4,
        "position": "DEF",
        "now_cost": 52,
    }

    checks = validate_replacement(squad, outgoing_id=3, incoming=incoming, bank=2)

    assert checks == {
        "player_available": True,
        "same_position": True,
        "within_budget": True,
        "club_limit": True,
        "squad_shape": True,
    }


def test_projection_penalizes_players_without_reliable_minutes() -> None:
    players = pd.DataFrame([
        {"id": 1, "team_id": 1, "form": 6.0, "ppg": 6.0, "ep_next": 6.0, "minutes": 360, "status": "a", "chance_of_playing": 100},
        {"id": 2, "team_id": 2, "form": 6.0, "ppg": 6.0, "ep_next": 6.0, "minutes": 0, "status": "a", "chance_of_playing": 100},
    ])

    projections = calculate_player_projections(players, pd.DataFrame(), next_gameweek=5, horizon=3).set_index("id")

    assert projections.loc[1, "projected_points"] > projections.loc[2, "projected_points"]


def test_transfer_gain_compares_best_legal_starting_eleven() -> None:
    squad = make_players()
    squad.loc[squad["id"] == 1, ["form", "ppg", "ep_next"]] = [6.0, 6.0, 6.0]
    squad.loc[squad["id"] == 2, ["form", "ppg", "ep_next"]] = [0.0, 0.0, 0.0]
    candidate = pd.DataFrame([{
        "id": 100,
        "web_name": "New goalkeeper",
        "team_id": 4,
        "team": "Team 4",
        "team_short": "T4",
        "position": "GKP",
        "now_cost": 50,
        "form": 8.0,
        "ppg": 8.0,
        "ep_next": 8.0,
        "minutes": 360,
        "status": "a",
        "chance_of_playing": 100,
    }])
    players = pd.concat([squad.drop(columns=["purchase_cost", "selling_price", "squad_pos"]), candidate], ignore_index=True)
    fixtures = make_fixtures()

    recommendations = recommend_transfers(squad, players, fixtures, bank=0, next_gameweek=5, horizon=3)
    move = recommendations[(recommendations["player_out_id"] == 2) & (recommendations["player_in_id"] == 100)].iloc[0]
    projections = calculate_player_projections(players, fixtures, next_gameweek=5, horizon=3).set_index("id")["projected_points"]

    assert move["projected_gain"] == round(projections.loc[100] - projections.loc[1], 2)
    assert move["projected_gain"] < move["player_in_projection"]
