from __future__ import annotations

import pandas as pd
import pytest

from fpl_data.recommendations import (
    PlannerSettings,
    build_manager_squad,
    calculate_selling_price,
    infer_free_transfers,
    infer_purchase_prices,
    plan_transfers,
    suggest_lineup,
    transfer_costs,
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
            "status": "a",
            "squad_pos": player_id,
        })
    return pd.DataFrame(rows)


def candidate(player_id: int, position: str, team_id: int, now_cost: int = 50, status: str = "a") -> dict:
    return {
        "id": player_id,
        "web_name": f"Candidate {player_id}",
        "team_id": team_id,
        "team": f"Team {team_id}",
        "team_short": f"T{team_id}",
        "position": position,
        "now_cost": now_cost,
        "status": status,
    }


def make_pool(squad: pd.DataFrame, candidates: list[dict]) -> pd.DataFrame:
    return pd.concat([squad.drop(columns=["purchase_cost", "selling_price", "squad_pos"]), pd.DataFrame(candidates)], ignore_index=True)


def make_xp(players: pd.DataFrame, gameweeks: list[int], values: dict[int, float] | None = None, default: float = 2.0) -> pd.DataFrame:
    values = values or {}
    return pd.DataFrame(
        {gameweek: [values.get(int(player_id), default) for player_id in players["id"]] for gameweek in gameweeks},
        index=players["id"].astype(int),
    )


def where(moves: pd.DataFrame, **ids: tuple[int, ...]) -> pd.DataFrame:
    mask = pd.Series(True, index=moves.index)
    for column, value in ids.items():
        mask &= moves[column].map(lambda item: item == value)
    return moves[mask]


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


def test_build_manager_squad_applies_sale_price_rule() -> None:
    players = make_pool(make_players(), []).assign(cost_change_start=0)
    players.loc[players["id"] == 3, ["now_cost", "cost_change_start"]] = [56, 6]
    picks = {"picks": [{"element": player_id, "position": player_id, "is_captain": player_id == 15, "is_vice_captain": False, "multiplier": 1} for player_id in range(1, 16)]}

    squad = build_manager_squad(players, picks, transfers=[], history_payload={})

    assert len(squad) == 15
    assert squad.loc[squad["id"] == 3, "selling_price"].item() == 53
    assert squad["squad_pos"].tolist() == list(range(1, 16))


def test_validate_squad_checks_official_shape_and_club_limit() -> None:
    squad = make_players()

    checks = validate_squad(squad)

    assert checks["fifteen_players"]
    assert checks["position_quota"]
    assert checks["club_limit"]


def test_validate_replacement_reports_every_transfer_rule() -> None:
    squad = make_players()
    incoming = {"id": 100, "team_id": 4, "position": "DEF", "now_cost": 52}

    checks = validate_replacement(squad, outgoing_id=3, incoming=incoming, bank=2)

    assert checks == {
        "player_available": True,
        "same_position": True,
        "within_budget": True,
        "club_limit": True,
        "squad_shape": True,
    }


def test_plan_uses_sale_price_plus_bank_in_tenths() -> None:
    squad = make_players()
    squad.loc[squad["id"] == 3, ["now_cost", "purchase_cost", "selling_price"]] = [55, 50, 52]
    pool = make_pool(squad, [candidate(100, "DEF", 4, now_cost=55), candidate(101, "DEF", 5, now_cost=56)])
    xp = make_xp(pool, [5, 6, 7], {3: 1.0, 100: 8.0, 101: 9.0})

    plan = plan_transfers(squad, pool, xp, bank=3)
    outgoing = where(plan.moves, out_ids=(3,))

    assert (100,) in outgoing["in_ids"].tolist()
    assert (101,) not in outgoing["in_ids"].tolist()
    move = where(outgoing, in_ids=(100,)).iloc[0]
    assert move["available_budget"] == 55
    assert move["bank_after"] == 0


def test_plan_preserves_position_and_three_player_club_limit() -> None:
    squad = make_players()
    pool = make_pool(squad, [candidate(100, "DEF", 1), candidate(101, "MID", 4)])
    xp = make_xp(pool, [5, 6, 7], {3: 1.0, 4: 1.0, 100: 8.0, 101: 9.0})

    moves = plan_transfers(squad, pool, xp, bank=0).moves

    assert where(moves, out_ids=(4,), in_ids=(100,)).empty
    assert not where(moves, out_ids=(3,), in_ids=(100,)).empty
    assert where(moves, out_ids=(3,))["in_ids"].tolist() == [(100,)]


def test_transfer_gain_includes_captaincy_and_best_starting_eleven() -> None:
    squad = make_players()
    pool = make_pool(squad, [candidate(100, "FWD", 4)])
    xp = make_xp(pool, [5], {100: 10.0})

    moves = plan_transfers(squad, pool, xp, bank=0).moves
    move = where(moves, in_ids=(100,)).iloc[0]

    assert move["xp_gain"] == pytest.approx(16.0)


def test_bench_upgrades_use_small_bench_weight() -> None:
    squad = make_players()
    pool = make_pool(squad, [candidate(100, "GKP", 4)])
    xp = make_xp(pool, [5], {1: 5.0, 2: 0.0, 100: 3.0})

    moves = plan_transfers(squad, pool, xp, bank=0).moves
    move = where(moves, out_ids=(2,), in_ids=(100,)).iloc[0]

    assert move["xp_gain"] == pytest.approx(0.03 * 3.0)


def test_injured_status_candidates_are_excluded_by_default() -> None:
    squad = make_players()
    pool = make_pool(squad, [candidate(100, "FWD", 4, status="d"), candidate(101, "FWD", 5)])
    xp = make_xp(pool, [5], {100: 9.0, 101: 4.0})

    default_moves = plan_transfers(squad, pool, xp, bank=0).moves
    doubtful_moves = plan_transfers(squad, pool, xp, bank=0, settings=PlannerSettings(allowed_statuses=frozenset({"a", "d"}))).moves

    assert (100,) not in default_moves["in_ids"].tolist()
    assert doubtful_moves.iloc[0]["in_ids"] == (100,)


def test_small_gain_recommends_rolling_the_free_transfer() -> None:
    squad = make_players()
    pool = make_pool(squad, [candidate(100, "FWD", 4)])
    xp = make_xp(pool, [5], {8: 10.0, 100: 3.0})

    plan = plan_transfers(squad, pool, xp, bank=0, settings=PlannerSettings(free_transfers=1))

    assert plan.moves.iloc[0]["weighted_gain"] == pytest.approx(1.0)
    assert plan.moves.iloc[0]["net_gain"] == pytest.approx(-0.5)
    assert plan.best is None


def test_two_transfer_search_respects_combined_budget_and_charges_hits() -> None:
    squad = make_players()
    pool = make_pool(squad, [candidate(100, "MID", 4, now_cost=60), candidate(101, "FWD", 5, now_cost=60), candidate(102, "FWD", 6, now_cost=50)])
    xp = make_xp(pool, [5, 6], {100: 9.0, 101: 9.0, 102: 6.0})

    plan = plan_transfers(squad, pool, xp, bank=15, settings=PlannerSettings(free_transfers=1, max_transfers=2))
    doubles = plan.moves[plan.moves["transfers"] == 2]

    assert not doubles.empty
    assert not any(set(move) == {100, 101} for move in doubles["in_ids"])
    assert (doubles["incoming_cost"] <= doubles["available_budget"]).all()
    assert (doubles["hits"] == 1).all()
    assert (doubles["hit_cost"] == 4).all()


@pytest.mark.parametrize(
    ("transfers", "free_transfers", "expected"),
    [(1, 1, (0, 0, 1.5)), (1, 5, (0, 0, 0.0)), (2, 1, (1, 4, 1.5)), (2, 2, (0, 0, 3.0)), (2, 5, (0, 0, 1.5))],
)
def test_transfer_costs_include_hits_and_banked_transfer_value(transfers: int, free_transfers: int, expected: tuple) -> None:
    assert transfer_costs(transfers, free_transfers) == expected


def test_infer_free_transfers_banks_up_to_five_and_keeps_them_on_chips() -> None:
    history = {
        "current": [
            {"event": 1, "event_transfers": 0},
            {"event": 2, "event_transfers": 0},
            {"event": 3, "event_transfers": 9},
            {"event": 4, "event_transfers": 0},
            {"event": 5, "event_transfers": 3},
            {"event": 6, "event_transfers": 0},
        ],
        "chips": [{"name": "wildcard", "event": 3}],
    }

    assert infer_free_transfers(history) == 3
    assert infer_free_transfers({"current": [{"event": gameweek, "event_transfers": 0} for gameweek in range(1, 10)]}) == 5
    assert infer_free_transfers({"current": []}) == 1


def test_suggest_lineup_picks_best_formation_captain_and_bench() -> None:
    squad = make_players()
    xp = {player_id: 2.0 for player_id in squad["id"]}
    xp.update({1: 4.0, 2: 1.0, 8: 9.0, 9: 6.0, 10: 6.0, 11: 6.0, 12: 6.0, 13: 0.5, 14: 0.4})

    lineup = suggest_lineup(squad, xp)

    assert lineup["formation"] == "4-5-1"
    assert lineup["captain"] == 8
    assert lineup["vice_captain"] in {9, 10, 11, 12}
    assert lineup["bench"][0] == 2
    assert len(lineup["starting"]) == 11
