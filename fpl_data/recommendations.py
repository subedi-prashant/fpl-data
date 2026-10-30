from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd

POSITION_QUOTAS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
FORMATIONS = [(3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 2, 3), (5, 3, 2), (5, 4, 1)]
# Defaults from the open-source FPL optimisation tools (Sertalp B. Cay / Solio Analytics).
BENCH_WEIGHTS = (0.03, 0.21, 0.06, 0.002)
DECAY_BASE = 0.84
FREE_TRANSFER_VALUE = 1.5
HIT_COST = 4
MAX_FREE_TRANSFERS = 5
MOVE_COLUMNS = [
    "transfers",
    "out_ids",
    "in_ids",
    "player_out",
    "player_in",
    "team_out",
    "team_in",
    "position",
    "selling_price",
    "incoming_cost",
    "available_budget",
    "bank_after",
    "xp_out",
    "xp_in",
    "xp_gain",
    "weighted_gain",
    "hits",
    "hit_cost",
    "ft_cost",
    "points_gain",
    "net_gain",
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


def build_manager_squad(
    players: pd.DataFrame,
    picks_payload: Mapping,
    transfers: Iterable[Mapping],
    history_payload: Mapping,
) -> pd.DataFrame:
    """Join a manager's public picks with player data and FPL sale prices."""
    picks = pd.DataFrame(picks_payload.get("picks", []))
    if picks.empty:
        return picks
    picks = picks.rename(columns={"element": "id", "position": "squad_pos"})
    picks = picks[["id", "squad_pos", "is_captain", "is_vice_captain", "multiplier"]]
    squad = picks.merge(players, on="id", how="left", validate="one_to_one")
    ignored_events = {
        int(chip["event"])
        for chip in history_payload.get("chips", [])
        if chip.get("name") == "freehit"
    }
    purchase_prices = infer_purchase_prices(squad["id"], players, transfers, ignored_events)
    squad["purchase_cost"] = squad["id"].map(purchase_prices).astype(int)
    squad["selling_price"] = [
        calculate_selling_price(now_cost, purchase_cost)
        for now_cost, purchase_cost in zip(squad["now_cost"], squad["purchase_cost"])
    ]
    return squad.sort_values("squad_pos").reset_index(drop=True)


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


def infer_free_transfers(history: Mapping, max_free_transfers: int = MAX_FREE_TRANSFERS) -> int:
    """Free transfers available for the next deadline, rebuilt from public gameweek history.

    One free transfer is added after every deadline (max five). Transfers beyond the bank
    cost points, and Wildcard/Free Hit weeks keep the banked transfers.
    """
    chips = {int(chip["event"]): chip.get("name") for chip in history.get("chips", []) if chip.get("event") is not None}
    free_transfers: int | None = None
    for entry in sorted(history.get("current", []), key=lambda item: int(item["event"])):
        event = int(entry["event"])
        if free_transfers is None:
            free_transfers = 1
        elif chips.get(event) in {"wildcard", "freehit"}:
            free_transfers = min(max_free_transfers, free_transfers + 1)
        else:
            used = int(entry.get("event_transfers", 0) or 0)
            free_transfers = min(max_free_transfers, max(free_transfers - used, 0) + 1)
    return free_transfers or 1


def transfer_costs(
    transfers: int,
    free_transfers: int,
    free_transfer_value: float = FREE_TRANSFER_VALUE,
    max_free_transfers: int = MAX_FREE_TRANSFERS,
) -> tuple[int, int, float]:
    """Return (hits, hit cost in points, value of banked free transfers given up)."""
    hits = max(0, transfers - free_transfers)
    banked_if_hold = min(max_free_transfers, free_transfers + 1)
    banked_if_move = min(max_free_transfers, max(free_transfers - transfers, 0) + 1)
    return hits, hits * HIT_COST, free_transfer_value * max(0, banked_if_hold - banked_if_move)


@dataclass(frozen=True)
class PlannerSettings:
    free_transfers: int = 1
    max_transfers: int = 1
    decay: float = DECAY_BASE
    free_transfer_value: float = FREE_TRANSFER_VALUE
    bench_weights: tuple[float, float, float, float] = BENCH_WEIGHTS
    allowed_statuses: frozenset[str] = frozenset({"a"})
    single_candidates: int = 30
    pair_candidates: int = 10


@dataclass
class TransferPlan:
    moves: pd.DataFrame
    hold_value: float
    hold_points: float
    gameweeks: list[int]
    settings: PlannerSettings = field(default_factory=PlannerSettings)

    @property
    def best(self) -> pd.Series | None:
        positive = self.moves[self.moves["net_gain"] > 0]
        return None if positive.empty else positive.iloc[0]


class _SquadEvaluator:
    """Score squads as best XI + captain + weighted bench, per gameweek, with time decay."""

    def __init__(self, decay: Iterable[float], bench_weights: tuple[float, float, float, float]) -> None:
        self.decay = np.asarray(list(decay), dtype=float)
        self.bench_gk_weight = bench_weights[0]
        self.bench_weights = np.asarray(bench_weights[1:], dtype=float)

    @staticmethod
    def prefix_sums(values: np.ndarray) -> np.ndarray:
        ordered = -np.sort(-values, axis=0) if len(values) else np.zeros((0, values.shape[1]))
        return np.vstack([np.zeros((1, values.shape[1])), np.cumsum(ordered, axis=0)])

    @staticmethod
    def top_sums(prefix: np.ndarray, inserts: list[np.ndarray], quota: int, batch: int) -> np.ndarray:
        horizon = prefix.shape[1]
        remaining = prefix.shape[0] - 1
        tops = np.full((quota + 1, batch, horizon), -np.inf)
        tops[0] = 0.0
        if len(inserts) == 2:
            high, low = np.maximum(inserts[0], inserts[1]), np.minimum(inserts[0], inserts[1])
            extra = [np.zeros((batch, horizon)), high, high + low]
        elif len(inserts) == 1:
            extra = [np.zeros((batch, horizon)), inserts[0]]
        else:
            extra = [np.zeros((batch, horizon))]
        for k in range(1, quota + 1):
            for taken, added in enumerate(extra):
                base = k - taken
                if 0 <= base <= remaining:
                    tops[k] = np.maximum(tops[k], prefix[base][None, :] + added)
        return tops

    def value(self, tops: Mapping[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        ranks = {position: np.diff(table, axis=0) for position, table in tops.items()}
        xi_options = []
        bench_options = []
        for defenders, midfielders, forwards in FORMATIONS:
            xi_options.append(tops["DEF"][defenders] + tops["MID"][midfielders] + tops["FWD"][forwards])
            bench_options.append(np.concatenate([ranks["DEF"][defenders:], ranks["MID"][midfielders:], ranks["FWD"][forwards:]], axis=0))
        xi = np.stack(xi_options)
        bench = np.stack(bench_options)
        chosen = np.argmax(xi, axis=0)
        outfield = np.take_along_axis(xi, chosen[None], axis=0)[0]
        bench_chosen = np.take_along_axis(bench, chosen[None, None], axis=0)[0]
        bench_sorted = -np.sort(-bench_chosen, axis=0)
        captain = np.max(np.stack([tops[position][1] for position in POSITION_QUOTAS]), axis=0)
        per_gameweek = (
            tops["GKP"][1]
            + outfield
            + captain
            + self.bench_gk_weight * (tops["GKP"][2] - tops["GKP"][1])
            + np.tensordot(self.bench_weights, bench_sorted, axes=(0, 0))
        )
        return per_gameweek @ self.decay, per_gameweek.sum(axis=1)


def suggest_lineup(squad: pd.DataFrame, xp: Mapping[int, float]) -> dict:
    """Best starting XI, captain and bench order for one gameweek of projections."""
    by_position = {
        position: sorted(
            [int(player_id) for player_id in squad.loc[squad["position"] == position, "id"]],
            key=lambda player_id: float(xp.get(player_id, 0.0)),
            reverse=True,
        )
        for position in POSITION_QUOTAS
    }
    best: tuple[float, tuple[int, int, int]] | None = None
    for formation in FORMATIONS:
        defenders, midfielders, forwards = formation
        if len(by_position["DEF"]) < defenders or len(by_position["MID"]) < midfielders or len(by_position["FWD"]) < forwards or not by_position["GKP"]:
            continue
        total = sum(float(xp.get(player_id, 0.0)) for player_id in by_position["DEF"][:defenders] + by_position["MID"][:midfielders] + by_position["FWD"][:forwards])
        if best is None or total > best[0]:
            best = (total, formation)
    if best is None:
        return {"starting": [], "bench": [], "captain": None, "vice_captain": None, "formation": "", "xi_points": 0.0}
    defenders, midfielders, forwards = best[1]
    starting = by_position["GKP"][:1] + by_position["DEF"][:defenders] + by_position["MID"][:midfielders] + by_position["FWD"][:forwards]
    outfield_bench = sorted(
        by_position["DEF"][defenders:] + by_position["MID"][midfielders:] + by_position["FWD"][forwards:],
        key=lambda player_id: float(xp.get(player_id, 0.0)),
        reverse=True,
    )
    ranked = sorted(starting, key=lambda player_id: float(xp.get(player_id, 0.0)), reverse=True)
    captain = ranked[0] if ranked else None
    xi_points = sum(float(xp.get(player_id, 0.0)) for player_id in starting) + (float(xp.get(captain, 0.0)) if captain else 0.0)
    return {
        "starting": starting,
        "bench": by_position["GKP"][1:] + outfield_bench,
        "captain": captain,
        "vice_captain": ranked[1] if len(ranked) > 1 else None,
        "formation": f"{defenders}-{midfielders}-{forwards}",
        "xi_points": round(xi_points, 2),
    }


def plan_transfers(
    squad: pd.DataFrame,
    players: pd.DataFrame,
    xp: pd.DataFrame,
    bank: int,
    settings: PlannerSettings = PlannerSettings(),
    position: str | None = None,
    required_out: int | None = None,
    keep_single: int = 25,
    keep_pair: int = 3,
) -> TransferPlan:
    """Search every legal 1- (and optionally 2-) transfer move and rank by net value.

    `xp` is a player x gameweek matrix of expected points. Each candidate squad is scored
    per gameweek as best XI + captain + weighted bench, discounted by `settings.decay`.
    Net value subtracts hits and the value of free transfers that would otherwise bank.
    The best `keep_single` replacements per outgoing player and `keep_pair` per outgoing
    pair are returned.
    """
    gameweeks = [int(gameweek) for gameweek in xp.columns]
    empty = TransferPlan(pd.DataFrame(columns=MOVE_COLUMNS), 0.0, 0.0, gameweeks, settings)
    if not gameweeks or not all(validate_squad(squad).values()):
        return empty
    evaluator = _SquadEvaluator(np.power(settings.decay, np.arange(len(gameweeks))), settings.bench_weights)
    matrix = xp.reindex(columns=gameweeks).fillna(0.0)
    xp_rows = {int(player_id): row for player_id, row in zip(matrix.index, matrix.to_numpy(dtype=float))}
    zero_row = np.zeros(len(gameweeks))
    xp_of = lambda player_ids: np.array([xp_rows.get(int(player_id), zero_row) for player_id in player_ids]).reshape(-1, len(gameweeks))

    squad = squad.copy()
    squad["id"] = squad["id"].astype(int)
    squad_ids = set(squad["id"])
    squad_by_position = {pos: squad.loc[squad["position"] == pos, "id"].tolist() for pos in POSITION_QUOTAS}
    full_prefix = {pos: evaluator.prefix_sums(xp_of(ids)) for pos, ids in squad_by_position.items()}
    hold_value, hold_points = evaluator.value({
        pos: evaluator.top_sums(full_prefix[pos], [], quota, 1) for pos, quota in POSITION_QUOTAS.items()
    })
    hold_value, hold_points = float(hold_value[0]), float(hold_points[0])

    weighted = pd.Series(matrix.to_numpy() @ evaluator.decay, index=matrix.index)
    pool = players[~players["id"].isin(squad_ids) & players["status"].isin(settings.allowed_statuses)].copy()
    pool["weighted_xp"] = pool["id"].map(weighted).fillna(0.0)
    pool = pool[pool["weighted_xp"] > 0].sort_values("weighted_xp", ascending=False)
    pool_by_position = {pos: pool[pool["position"] == pos] for pos in POSITION_QUOTAS}
    lookup = pd.concat([squad, pool]).drop_duplicates("id").set_index("id")
    position_of = lookup["position"].to_dict()
    team_of = lookup["team_id"].astype(int).to_dict()
    cost_of = lookup["now_cost"].astype(int).to_dict()
    name_of = lookup["web_name"].astype(str).to_dict()
    short_of = lookup["team_short"].astype(str).to_dict()
    club_counts = Counter(squad["team_id"].astype(int))
    selling = squad.set_index("id")["selling_price"].astype(int).to_dict()

    outgoing = [player_id for player_id in squad["id"] if position is None or position_of[player_id] == position]
    rows: list[dict] = []

    def record(out_ids: tuple[int, ...], combos: list[tuple[int, ...]], keep: int) -> None:
        if not combos:
            return
        out_positions = [position_of[player_id] for player_id in out_ids]
        tops = {}
        for pos, quota in POSITION_QUOTAS.items():
            slots = [index for index, out_position in enumerate(out_positions) if out_position == pos]
            if not slots:
                tops[pos] = evaluator.top_sums(full_prefix[pos], [], quota, len(combos))
                continue
            remaining = [player_id for player_id in squad_by_position[pos] if player_id not in out_ids]
            inserts = [xp_of([combo[slot] for combo in combos]) for slot in slots]
            tops[pos] = evaluator.top_sums(evaluator.prefix_sums(xp_of(remaining)), inserts, quota, len(combos))
        values, points = evaluator.value(tops)
        budget = sum(selling[player_id] for player_id in out_ids) + int(bank)
        hits, hit_cost, ft_cost = transfer_costs(len(out_ids), settings.free_transfers, settings.free_transfer_value)
        xp_out = float(xp_of(out_ids).sum())
        for index in np.argsort(-values, kind="stable")[:keep]:
            combo = combos[index]
            cost = sum(cost_of[player_id] for player_id in combo)
            rows.append({
                "transfers": len(out_ids),
                "out_ids": tuple(out_ids),
                "in_ids": tuple(combo),
                "player_out": ", ".join(name_of[player_id] for player_id in out_ids),
                "player_in": ", ".join(name_of[player_id] for player_id in combo),
                "team_out": ", ".join(short_of[player_id] for player_id in out_ids),
                "team_in": ", ".join(short_of[player_id] for player_id in combo),
                "position": ", ".join(out_positions),
                "selling_price": budget - int(bank),
                "incoming_cost": cost,
                "available_budget": budget,
                "bank_after": budget - cost,
                "xp_out": xp_out,
                "xp_in": float(xp_of(combo).sum()),
                "xp_gain": round(float(points[index]) - hold_points, 2),
                "weighted_gain": round(float(values[index]) - hold_value, 2),
                "hits": hits,
                "hit_cost": hit_cost,
                "ft_cost": ft_cost,
            })

    def legal(out_ids: tuple[int, ...], in_ids: tuple[int, ...]) -> bool:
        counts = club_counts.copy()
        for player_id in out_ids:
            counts[team_of[player_id]] -= 1
        for player_id in in_ids:
            counts[team_of[player_id]] += 1
        return max(counts.values()) <= 3

    for out_id in outgoing:
        if required_out is not None and out_id != required_out:
            continue
        budget = selling[out_id] + int(bank)
        picks: list[tuple[int, ...]] = []
        for candidate_id, candidate_cost in zip(pool_by_position[position_of[out_id]]["id"], pool_by_position[position_of[out_id]]["now_cost"]):
            if int(candidate_cost) <= budget and legal((out_id,), (int(candidate_id),)):
                picks.append((int(candidate_id),))
                if len(picks) >= settings.single_candidates:
                    break
        record((out_id,), picks, keep_single)

    if settings.max_transfers >= 2:
        shortlist = {}
        for pos, candidates in pool_by_position.items():
            value_order = candidates.assign(per_cost=candidates["weighted_xp"] / candidates["now_cost"]).sort_values("per_cost", ascending=False)
            chosen = pd.concat([candidates.head(settings.pair_candidates), value_order.head(settings.pair_candidates)]).drop_duplicates("id")
            shortlist[pos] = [(int(player_id), int(cost)) for player_id, cost in zip(chosen["id"], chosen["now_cost"])]
        for first, second in combinations(outgoing, 2):
            if required_out is not None and required_out not in (first, second):
                continue
            budget = selling[first] + selling[second] + int(bank)
            first_pos, second_pos = position_of[first], position_of[second]
            pairs = combinations(shortlist[first_pos], 2) if first_pos == second_pos else ((a, b) for a in shortlist[first_pos] for b in shortlist[second_pos])
            picks = [
                (a[0], b[0])
                for a, b in pairs
                if a[1] + b[1] <= budget and legal((first, second), (a[0], b[0]))
            ]
            record((first, second), picks, keep_pair)

    if not rows:
        return TransferPlan(pd.DataFrame(columns=MOVE_COLUMNS), hold_value, hold_points, gameweeks, settings)
    moves = pd.DataFrame(rows)
    moves["points_gain"] = (moves["xp_gain"] - moves["hit_cost"]).round(2)
    moves["net_gain"] = (moves["weighted_gain"] - moves["hit_cost"] - moves["ft_cost"]).round(2)
    moves = moves.sort_values(["net_gain", "xp_gain", "bank_after"], ascending=[False, False, False]).reset_index(drop=True)
    return TransferPlan(moves[MOVE_COLUMNS], hold_value, hold_points, gameweeks, settings)
