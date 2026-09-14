from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

import pandas as pd

POSITION_QUOTAS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
DIFFICULTY_MULTIPLIERS = {1: 1.18, 2: 1.09, 3: 1.0, 4: 0.91, 5: 0.82}
RECOMMENDATION_COLUMNS = [
    "player_out_id",
    "player_out",
    "team_out",
    "player_in_id",
    "player_in",
    "team_in",
    "position",
    "selling_price",
    "incoming_cost",
    "available_budget",
    "bank_after",
    "player_out_projection",
    "player_in_projection",
    "projected_gain",
    "current_lineup_projection",
    "new_lineup_projection",
    "outgoing_starts",
    "incoming_starts",
    "out_status",
    "in_status",
    "out_squad_pos",
]


def calculate_selling_price(now_cost: int, purchase_cost: int) -> int:
    now_cost = int(now_cost)
    purchase_cost = int(purchase_cost)
    if now_cost <= purchase_cost:
        return now_cost
    return purchase_cost + (now_cost - purchase_cost) // 2


def infer_purchase_prices(
    squad_player_ids: Iterable[int],
    players: pd.DataFrame,
    transfers: Iterable[Mapping],
    ignored_events: set[int] | None = None,
) -> dict[int, int]:
    ignored_events = ignored_events or set()
    player_lookup = players.set_index("id")
    valid_transfers = [
        transfer
        for transfer in transfers
        if int(transfer.get("event", 0)) not in ignored_events
    ]
    prices = {}
    for player_id in squad_player_ids:
        player_id = int(player_id)
        player = player_lookup.loc[player_id]
        starting_price = int(player["now_cost"]) - int(player.get("cost_change_start", 0))
        incoming = [
            transfer
            for transfer in valid_transfers
            if int(transfer.get("element_in", -1)) == player_id
            and transfer.get("element_in_cost") is not None
        ]
        if incoming:
            latest = max(
                incoming,
                key=lambda transfer: (
                    str(transfer.get("time", "")),
                    int(transfer.get("event", 0)),
                ),
            )
            prices[player_id] = int(latest["element_in_cost"])
        else:
            prices[player_id] = starting_price
    return prices


def validate_squad(squad: pd.DataFrame) -> dict[str, bool]:
    position_counts = squad["position"].value_counts().to_dict() if "position" in squad else {}
    club_counts = squad["team_id"].value_counts() if "team_id" in squad else pd.Series(dtype="int64")
    return {
        "fifteen_players": len(squad) == 15 and squad["id"].nunique() == 15,
        "position_quota": all(position_counts.get(position, 0) == count for position, count in POSITION_QUOTAS.items()),
        "club_limit": club_counts.empty or int(club_counts.max()) <= 3,
    }


def validate_replacement(
    squad: pd.DataFrame,
    outgoing_id: int,
    incoming: Mapping,
    bank: int,
) -> dict[str, bool]:
    outgoing_rows = squad[squad["id"] == outgoing_id]
    if outgoing_rows.empty:
        return {
            "player_available": False,
            "same_position": False,
            "within_budget": False,
            "club_limit": False,
            "squad_shape": False,
        }
    outgoing = outgoing_rows.iloc[0]
    squad_ids = set(squad["id"].astype(int))
    incoming_id = int(incoming["id"])
    selling_price = int(outgoing.get("selling_price", calculate_selling_price(outgoing["now_cost"], outgoing.get("purchase_cost", outgoing["now_cost"]))))
    player_available = incoming_id not in squad_ids
    same_position = str(outgoing["position"]) == str(incoming["position"])
    within_budget = int(incoming["now_cost"]) <= selling_price + int(bank)
    club_counts = Counter(squad["team_id"].astype(int))
    club_counts[int(outgoing["team_id"])] -= 1
    club_counts[int(incoming["team_id"])] += 1
    club_limit = max(club_counts.values(), default=0) <= 3
    position_counts = Counter(squad["position"].astype(str))
    position_counts[str(outgoing["position"])] -= 1
    position_counts[str(incoming["position"])] += 1
    squad_shape = len(squad) == 15 and all(position_counts[position] == count for position, count in POSITION_QUOTAS.items())
    return {
        "player_available": bool(player_available),
        "same_position": bool(same_position),
        "within_budget": bool(within_budget),
        "club_limit": bool(club_limit),
        "squad_shape": bool(squad_shape),
    }


def calculate_player_projections(
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    next_gameweek: int,
    horizon: int,
) -> pd.DataFrame:
    projected = players.copy()
    for column in ["form", "ppg", "ep_next", "minutes"]:
        if column not in projected:
            projected[column] = 0.0
        projected[column] = pd.to_numeric(projected[column], errors="coerce").fillna(0.0)
    completed_gameweeks = max(1, next_gameweek - 1)
    fixture_map: dict[tuple[int, int], list[int]] = {}
    if not fixtures.empty:
        event_column = "event" if "event" in fixtures else "gw"
        home_column = "team_h_id" if "team_h_id" in fixtures else "team_h"
        away_column = "team_a_id" if "team_a_id" in fixtures else "team_a"
        selected_fixtures = fixtures[
            fixtures[event_column].isin(range(next_gameweek, next_gameweek + horizon))
        ]
        for fixture in selected_fixtures.to_dict("records"):
            event = int(fixture[event_column])
            home_team = int(fixture[home_column])
            away_team = int(fixture[away_column])
            fixture_map.setdefault((home_team, event), []).append(int(fixture["team_h_difficulty"]))
            fixture_map.setdefault((away_team, event), []).append(int(fixture["team_a_difficulty"]))

    def availability(row: pd.Series) -> float:
        status = str(row.get("status", "a"))
        chance = pd.to_numeric(row.get("chance_of_playing", None), errors="coerce")
        if pd.notna(chance):
            return max(0.0, min(1.0, float(chance) / 100.0))
        return 1.0 if status == "a" else 0.75 if status == "d" else 0.0

    def player_projection(row: pd.Series) -> float:
        base_points = float(row["form"]) * 0.55 + float(row["ppg"]) * 0.30 + float(row["ep_next"]) * 0.15
        total = 0.0
        for offset in range(horizon):
            gameweek = next_gameweek + offset
            difficulties = fixture_map.get((int(row["team_id"]), gameweek), [])
            if fixtures.empty:
                difficulties = [3]
            weight = 0.85 ** offset
            total += sum(base_points * DIFFICULTY_MULTIPLIERS.get(difficulty, 1.0) * weight for difficulty in difficulties)
        minute_share = min(1.0, float(row["minutes"]) / (completed_gameweeks * 90))
        reliability = 0.65 + minute_share * 0.35
        return round(total * availability(row) * reliability, 2)

    projected["projected_points"] = projected.apply(player_projection, axis=1)
    return projected


def optimal_lineup_projection(players: pd.DataFrame | Iterable[Mapping]) -> tuple[float, set[int]]:
    records = players.to_dict("records") if isinstance(players, pd.DataFrame) else list(players)
    by_position = {
        position: sorted(
            [player for player in records if player["position"] == position],
            key=lambda player: float(player["projected_points"]),
            reverse=True,
        )
        for position in POSITION_QUOTAS
    }
    if not by_position["GKP"]:
        return 0.0, set()
    best_score = -1.0
    best_ids: set[int] = set()
    goalkeeper = by_position["GKP"][0]
    for defender_count in range(3, 6):
        for midfielder_count in range(2, 6):
            forward_count = 10 - defender_count - midfielder_count
            if forward_count < 1 or forward_count > 3:
                continue
            if len(by_position["DEF"]) < defender_count or len(by_position["MID"]) < midfielder_count or len(by_position["FWD"]) < forward_count:
                continue
            lineup = [goalkeeper]
            lineup.extend(by_position["DEF"][:defender_count])
            lineup.extend(by_position["MID"][:midfielder_count])
            lineup.extend(by_position["FWD"][:forward_count])
            score = sum(float(player["projected_points"]) for player in lineup)
            if score > best_score:
                best_score = score
                best_ids = {int(player["id"]) for player in lineup}
    return round(max(0.0, best_score), 2), best_ids


def recommend_transfers(
    squad: pd.DataFrame,
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    bank: int,
    next_gameweek: int,
    horizon: int = 3,
    position: str | None = None,
    include_doubtful: bool = False,
) -> pd.DataFrame:
    if not all(validate_squad(squad).values()):
        return pd.DataFrame(columns=RECOMMENDATION_COLUMNS)
    projections = calculate_player_projections(players, fixtures, next_gameweek, horizon)
    if "status" not in projections:
        projections["status"] = "a"
    projection_lookup = projections.set_index("id")["projected_points"].to_dict()
    squad_ids = set(squad["id"].astype(int))
    squad_records = squad.to_dict("records")
    for player in squad_records:
        player["projected_points"] = float(projection_lookup.get(int(player["id"]), 0.0))
    current_lineup_projection, current_lineup_ids = optimal_lineup_projection(squad_records)
    candidates = projections[~projections["id"].isin(squad_ids)].copy()
    allowed_statuses = {"a", "d"} if include_doubtful else {"a"}
    candidates = candidates[candidates["status"].isin(allowed_statuses)]
    if include_doubtful and "chance_of_playing" in candidates:
        chance = pd.to_numeric(candidates["chance_of_playing"], errors="coerce").fillna(100)
        candidates = candidates[(candidates["status"] == "a") | (chance >= 75)]
    candidates_by_position = {
        player_position: candidates[candidates["position"] == player_position].to_dict("records")
        for player_position in POSITION_QUOTAS
    }
    club_counts = Counter(squad["team_id"].astype(int))
    rows = []
    for outgoing in squad_records:
        if position and outgoing["position"] != position:
            continue
        outgoing_id = int(outgoing["id"])
        outgoing_team = int(outgoing["team_id"])
        selling_price = int(outgoing.get("selling_price", calculate_selling_price(outgoing["now_cost"], outgoing.get("purchase_cost", outgoing["now_cost"]))))
        available_budget = selling_price + int(bank)
        remaining_squad = [player for player in squad_records if int(player["id"]) != outgoing_id]
        for incoming in candidates_by_position[outgoing["position"]]:
            incoming_cost = int(incoming["now_cost"])
            if incoming_cost > available_budget:
                continue
            incoming_team = int(incoming["team_id"])
            incoming_club_count = club_counts[incoming_team] + 1 - int(incoming_team == outgoing_team)
            if incoming_club_count > 3:
                continue
            new_lineup_projection, new_lineup_ids = optimal_lineup_projection([*remaining_squad, incoming])
            incoming_id = int(incoming["id"])
            outgoing_projection = float(outgoing["projected_points"])
            incoming_projection = float(incoming["projected_points"])
            rows.append({
                "player_out_id": outgoing_id,
                "player_out": outgoing["web_name"],
                "team_out": outgoing["team_short"],
                "player_in_id": incoming_id,
                "player_in": incoming["web_name"],
                "team_in": incoming["team_short"],
                "position": outgoing["position"],
                "selling_price": selling_price,
                "incoming_cost": incoming_cost,
                "available_budget": available_budget,
                "bank_after": available_budget - incoming_cost,
                "player_out_projection": outgoing_projection,
                "player_in_projection": incoming_projection,
                "projected_gain": round(new_lineup_projection - current_lineup_projection, 2),
                "current_lineup_projection": current_lineup_projection,
                "new_lineup_projection": new_lineup_projection,
                "outgoing_starts": outgoing_id in current_lineup_ids,
                "incoming_starts": incoming_id in new_lineup_ids,
                "out_status": outgoing.get("status", "a"),
                "in_status": incoming.get("status", "a"),
                "out_squad_pos": int(outgoing.get("squad_pos", 15)),
            })
    if not rows:
        return pd.DataFrame(columns=RECOMMENDATION_COLUMNS)
    return (
        pd.DataFrame(rows)
        .sort_values(["projected_gain", "player_in_projection", "bank_after"], ascending=[False, False, False])
        .reset_index(drop=True)
    )
